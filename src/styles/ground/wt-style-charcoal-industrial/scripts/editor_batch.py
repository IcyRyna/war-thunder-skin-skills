"""Serialize complete owned Composa batches across independent vehicle tasks."""
from pathlib import Path
import argparse,contextlib,math,os,subprocess,sys,tempfile,time

@contextlib.contextmanager
def editor_lock(timeout=180):
 path=Path(tempfile.gettempdir())/'wt-composa-owned-batch.lock';stream=path.open('a+b');stream.seek(0,2)
 if stream.tell()==0:stream.write(b'0');stream.flush()
 deadline=time.monotonic()+timeout;locked=False
 try:
  while not locked:
   try:
    stream.seek(0)
    if os.name=='nt':
     import msvcrt
     msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
    else:
     import fcntl
     fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    locked=True
   except OSError:
    if time.monotonic()>=deadline:raise TimeoutError('Another vehicle owns the editor; no Composa calls were sent')
    time.sleep(.25)
  yield
 finally:
  if locked:
   stream.seek(0)
   if os.name=='nt':
    import msvcrt
    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
   else:
    import fcntl
    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
  stream.close()

def build_command(args):
 if not math.isfinite(args.lock_timeout) or args.lock_timeout<=0 or not math.isfinite(args.timeout) or not 1<=args.timeout<=60:
  raise ValueError('Lock timeout must be finite/positive; request timeout must be 1..60 seconds')
 command=[sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('composa_mcp.py')),'--out',str(args.out),'--timeout',str(args.timeout)]
 if args.calls:command+=['--calls',str(args.calls)]
 if args.exe:command+=['--exe',str(args.exe)]
 if args.keep_open:command.append('--keep-open')
 return command

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calls',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--lock-timeout',type=float,default=180);p.add_argument('--timeout',type=float,default=60)
 p.add_argument('--exe',type=Path);p.add_argument('--keep-open',action='store_true');a=p.parse_args()
 command=build_command(a)
 with editor_lock(a.lock_timeout):
  result=subprocess.run(command,check=False)
 raise SystemExit(result.returncode)
if __name__=='__main__':main()
