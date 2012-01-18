#!/usr/bin/python3
# Author: NssY Wanyonyi
# Purpose: Encode Multiple Files to mp4 (h264/aac)
# Date: 3rd Jan 2012
# Works on Windows and Linux (should work on mac but not tested)
# Requries ffmpeg (with h264 support)

import subprocess, sys, os, atexit, re, platform, ctypes, shutil
from time import sleep, time
from datetime import datetime, timedelta
from socket import gethostname

def main():
  # Sanity Check
  if len(sys.argv) >= 2:
    app = BatchEnc(folder = sys.argv[1])
    app.process_batch()
  else:
    print(' -> Please specify the source folders with videos')
      
class BatchEnc:

    def __init__(self, **kwargs):
        # Configs
        self.machine = gethostname()
        self.ffmpeg = '/usr/bin/ffmpeg'
        if platform.system() == 'Windows':
            self.ffmpeg = "C:/Windows/System32/ffmpeg.exe"
        self.version = "0.0.2"
        self.appname = "h264-batch-encode.py"
        self.pid = str(os.getpid())
        # Match the extensions (ignore case)
        
        self.allowed_ext = [".dat", ".flv", ".mp4", ".mpeg"]
        #self.allowed_ext = [".mpeg"]
        
        # Sanity Checks
        if not os.path.isfile(self.ffmpeg):
            print('Cannot Locate '+self.ffmpeg)
            sys.exit()
        self.comment="Done By "+ self.appname +' '+ self.version # This Appears on metadata of output file
        self.verbose=1 # (either 0 or 1) Show window Progress Details when encoding
        self.overwrite=1 # (either 0 or 1) Overwrites the output file if it exists
        self.timelimit = 0 # If this is set all output videos will be set to this length

        # Paths - Directories
        self.indir = kwargs['folder']
        print(self.indir)
        self.outdir=os.path.expanduser('~')+"/Videos/mp4batch"
        self.tmpdir=self.outdir+"/h264-batch-tmp"
        
        # On Windows (we have to include trailing slashes)
        #if platform.system() == 'Windows':
        #    self.indir="D:"+os.sep
        #    self.outdir="E:"+os.sep
        #    self.tmpdir="D:"+os.sep+"tmp"+os.sep
            
        # Log Folder
        self.logdir=os.path.join(self.indir,'logs')
        # Create all non existent directories
        self.makedirs(self.outdir)
        self.makedirs(self.tmpdir)
        self.makedirs(self.logdir)

        # Paths - Files
        self.applogfile  = os.path.join(self.indir, "h264-batch-encode-log") # Just used for benchmarking
        self.apperrorfile = os.path.join(self.indir, "h264-batch-encode-error-log") # Log every error to a file
        self.batchfile = os.path.join(self.tmpdir, "h264_batch_encode.txt") # This store a list of all files selected for processing (Used to prevent multiple encoding on the same file)
        self.encodelogfile = os.path.join(self.tmpdir, "ffmpeg_" + self.pid) # stores ffmpeg output
        self.passfile = os.path.join(self.tmpdir, "x264_2pass." + self.pid) # Set pass file for ffmpeg. 
        
        # File Handles
        self.log = open(self.applogfile, 'a')
        self.errorlog = open(self.apperrorfile, 'a')
        self.batchfilelog = open(self.batchfile, 'a')
        self.ffmpeglog = open(self.encodelogfile, 'a')
        
        # Output File type
        self.output_ext = '.mp4'
        
        ################################
        ### BATCH MODE OPTIONS ###
        ################################
        # Minimum Free Space (bytes) in output folder
        self.minfree=512000

        ################################
        ### FFMPEG Encoding Options ###
        ###############################
        
        self.ffmpeg_options = dict(

            # BASIC FFMPEG Options (see ffmpeg -formats)
            BASIC = [
                '-acodec','libfaac',
                '-ab','110k',
                '-ar','48000',
                '-f','mp4',
                '-vcodec','libx264', 
                '-maxrate','2.5M',
                '-b','760k',
                #'-s','352x288'
            ],
            H264 = [
                '-coder','0', '-flags','+loop+mv0+slice' ,'-cmp','+chroma',
                '-partitions','+parti8x8+parti4x4+partp8x8+partb8x8' ,'-g','250',
                '-me_method','full','-subq','6' ,'-me_range','16','-bf','8',
                '-qmin','1' ,'-qmax','51', '-qdiff','3','-qcomp','0.6',
                '-refs','2' ,'-directpred','2', '-i_qfactor','0.71428572',
                '-sc_threshold','40' ,'-keyint_min','25', '-b_strategy','1',
                '-trellis','0'
            ],
            
            # TODO: Presets (Implement This on windows)
            PRESET_PASS1=['-vpre', 'libx264-tv-recorded-backup-pass1'],
            PRESET_PASS2=['-vpre', 'libx264-tv-recorded-backup-pass2'],

            # Long Method without Presets (set Different options for pass1, pass2)
            PASS1 = ['-flags2','+bpyramid+wpred+mixed_refs+wpred+fastpskip'],
            PASS2 = ['-flags2','+bpyramid+wpred+mixed_refs'],
            
            # ADVANCED FFMPEG Options
            ADVANCED = ['-bt', '175k', '-threads', '0', '-cmp', '1', '-mbd', '2', '-v', '1', '-deblockalpha', '0', '-deblockbeta', '0']
        )
        
    def makedirs(self, p):
        if p and not os.path.isdir(p):
          os.makedirs(p)
          
    def get_free_space(self, folder):
        if platform.system() == 'Windows':
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free_bytes))
            return free_bytes.value / 1024
        else:
            s = os.statvfs(folder)
            return s.f_bsize * s.f_bavail / 1024

    def humanize_time(self, secs): 
        d = timedelta(seconds=secs) 
        return str(d)

    def validate_files(self):
        filelist = {}
        i = 0
        filelist_raw = ''
        # Sort according to date TODO: Get this to work on windows
        # s = sorted(filter(os.path.isdir, os.listdir(self.indir)), key=os.path.getmtime)
        
        s = os.listdir(self.indir)
        
        # Get valid files
        for e in s:
            if not os.path.isdir(e):
                # Match the extensions required (ignore case)
                ext = os.path.splitext(e)[1].lower()
                if ext in self.allowed_ext:
                    infile = os.path.join(self.indir,e)
                    filelist[int(os.path.getmtime(infile))] = infile
                    filelist_raw += infile+'\r\n'
            i+=1
        
        self.batchfilelog.writelines(filelist_raw)
        return filelist

    def cleanup(self):
        print(' -> Some House keeping...!')
        self.log.close()
        os.unlink(self.applogfile)
        self.errorlog.close()
        os.unlink(self.apperrorfile)
        self.batchfilelog.close()
        os.unlink(self.batchfile)
        self.ffmpeglog.close()
        os.unlink(self.encodelogfile)
        os.unlink(self.passfile)
        
    def get_details(self, infile):
        command = ["ffmpeg","-i",infile]
        process = subprocess.Popen(args=command,stdout=subprocess.PIPE,
                    stdin=subprocess.PIPE,stderr=subprocess.STDOUT)
        output = str(process.stdout.read())
        output = output.replace('\n','')
        output_split = output.split(' ')
        N=len(output_split)
        r = re.compile('(\d+):(\d+):(\d+).(\d+)')
        duration = 0
        for i in range(N):
          # Grab Duration of audio/video
          match = r.search(output_split[i])
          if i>=1 and match:
            h = match.group(1)
            m = match.group(2)
            s = match.group(3)
            ms = match.group(4)
            # Calculate length (Play time) of Clip in seconds               
            duration=3600*float(h)+\
              60*float(m)+\
              float(s) + float(ms) / 100
        return duration

    def prep_filenames(self, infile):
        basename = os.path.basename(infile)
        bare_name = os.path.splitext(basename)[0]
        file_date = datetime.fromtimestamp(os.path.getmtime(infile))
        short_date = file_date.strftime('%d%m%y')
        extension = os.path.splitext(infile)[1]
        file_month = file_date.strftime('%B')
        file_year = file_date.strftime('%Y')
        file_month_year = file_month+'-'+file_year
        out_tag = bare_name+' '+file_date.strftime('%a-%d-%b %H.%M.%S')
        title_tag = bare_name+' ('+str(file_date)+')'
        bare_outfile = short_date+'_'+out_tag+self.output_ext
        
        # Input
        self.infile = infile
        # Output
        self.tempfile1 = os.path.join(self.tmpdir, bare_outfile)
        outmonth_dir = os.path.join(self.outdir, file_month_year)
        self.makedirs(outmonth_dir)
        self.outfile = os.path.join(outmonth_dir, bare_outfile)
        # Metadata
        self.title_tag = title_tag
        # Done
        done_dir = os.path.join(self.indir, 'done', file_month_year)
        self.makedirs(done_dir)
        self.donefile = os.path.join(done_dir, short_date+'_'+bare_name+extension)
        
        # XML Logging
        self.xml_log_file = os.path.join(self.logdir, file_month_year+'.xml')
        
    # The Batch Process start here              
    def process_batch(self):
        print(' -> Processing Batch from', self.indir)
        validlist = self.validate_files()
        total_files = len(validlist)
        if total_files > 0:
            print(' -> Added',total_files ,'Valid Videos',end="\n\n")
        else:
            print(' -> No Valid Videos. Expecting ..', self.allowed_ext)
            return 0
        i = 1
        for k in sorted(validlist.keys()):
            file = validlist[k]
            
            # Check Free space on output folder
            f = self.get_free_space(self.outdir)
            if f > self.minfree:
                print(' -> Free Space is',round(f/1024,2),'MB. (Proceeding ...)')
            else:
                print(' -> Out of space in ', self.outdir)
                return None
            timelimit = self.get_details(file)
            self.prep_filenames(file)
            # Force Specific time limit (Testing only)
            if self.timelimit > 0:
                timelimit = self.timelimit
            print(' -> (File ',i,' of',total_files,')')
            self.log.write('Working on File '+file+"\r\n")
            es = self.convert(timelimit)
            if es == 0:
                self.post_encode(timelimit)
                self.parse_xml()
            i+=1
        self.cleanup()
    def progressBar(self, p, clip_length, passVar):
        percentage = 0
        t_start = time()
        enc_periodic = 0
        r1 = re.compile('time=(\d+.\d+)') # Older ffmpeg (showed seconds)
        r2 = re.compile('time=(\d+:\d+:\d+.\d+)') # Newer ffmpeg (Shows hh:mm:ss:ms)
        read_buffer = 128
        t_elapsed = 0
        while percentage < 100:
          enc_done = 0
          if p.poll():
            # subprocess p ended prematurely
            #TODO: Give details of exception
            print(' -> ffmpeg ended prematurely on pass',passVar,'.....')
            return 1
          elif not p.stdout.read(read_buffer):
              # No output (Encoding must be over)
              percentage = 100
              sleep(0.1)
          else:
              output = str(p.stdout.read(read_buffer))
              output = output.replace('\r','')
              output_split = output.split(' ')
              N=len(output_split)
              for i in range(N):
                m1 = r1.search(output_split[i])
                m2 = r2.search(output_split[i])
                if i>=1 and m1:
                  try:
                    enc_done = float(m1.group(1))
                  except (ValueError, KeyError):
                    enc_done = 0
                    if i>=1 and m2:
                      try:
                        t = m2.group(1).split('.')[0]
                        enc_done = sum(int(x) * 60 ** i for i,x in enumerate(reversed(t.split(":"))))
                      except (ValueError, KeyError):
                        enc_done = 0
                  #print(enc_done)
                
              # Prevent Division by zero
              if int(enc_done) > 0:
                t_now = time()
                enc_remaining = clip_length - enc_done
                t_elapsed = round(t_now - t_start)
                
                # TODO: Avarage the values of t for greater accuracy
                t_remaining = round(t_elapsed * enc_remaining / enc_done)
                percentage = 100 * enc_done / clip_length
                print(str(round(percentage,1))+'%',' | ELAPSED [',self.humanize_time(t_elapsed),'] | ETA [',self.humanize_time(t_remaining),"]   \r",end="")
                sys.stdout.flush()
              sleep(0.5)
        print("\n -> Pass", passVar, "Completed in", t_elapsed,'Sec(s)')
        return 0

    def convert(self, time):
        es1 = self.h264enc(1, time)
        # Check Exit Status Before We Proceed
        if es1 == 0:
            es2 = self.h264enc(2, time)
            if es2 == 0:
                return 0
            else:
                return 1
        else:
            # Pass 1 failed
            print(' -> Skipping Pass2..!')
            return 1
            
    def h264enc(self, passVar, time):
        if passVar == 1:
            pass_options = self.ffmpeg_options['PASS1']
            outfile = os.devnull
        else:
            pass_options = self.ffmpeg_options['PASS2']
            outfile = self.tempfile1
        
        print(' -> Pass',passVar,"[",self.title_tag,"]",end="\n")
        if time > 0:
            time_param = ["-t", str(time)]
        else:
            time_param = None
            
        command = ['ffmpeg',"-y","-i",str(self.infile), "-pass",str(passVar)]
        command += time_param
        command += ['-metadata','title='+self.title_tag,'-metadata','comment='+self.comment]
        command += ['-passlogfile',self.passfile]
        command += self.ffmpeg_options['BASIC'] + self.ffmpeg_options['H264']
        command += self.ffmpeg_options['ADVANCED']
        command += pass_options
        command.append(outfile)
        # Output ffmpeg command to user
        raw_command = ''
        for var in command:
            raw_command += var +' '
        print(raw_command, '\n')
        
        # Encoding Starts Here
        process = subprocess.Popen(args=command, bufsize=0,stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
        es = self.progressBar(process, time, passVar)
        self.ffmpeglog.write('Pass:'+str(passVar)+' \r\n'+raw_command+'\r\n')
        return es
        
    def post_encode(self, time):
        print(' -> Moving Output file to ',self.outfile)
        shutil.move(self.tempfile1, self.outfile)
        if not os.path.isfile(self.tempfile1):
            if self.get_details(self.outfile) >= time-1:
                print(' -> Now Moving Input file to ',self.donefile)
                shutil.move(self.infile, self.donefile)
            else:
                print(' -> Output Video is Not Complete. Leaving Input Video Intact')
        else:
            print("-> Output File hasn't Moved")

    def parse_xml(self):
        self.xml_handle = open(self.xml_log_file, 'a')
        self.xml_handle.close()
          
# Ok We start Main
if __name__ == '__main__': main()
  
  
