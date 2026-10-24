"""Serialize complete owned Composa batches across independent vehicle tasks."""
from pathlib import Path
import argparse,contextlib,os,subprocess,sys,tempfile,time

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

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calls',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--lock-timeout',type=float,default=180);p.add_argument('--timeout',type=float,default=60);a=p.parse_args()
 if a.lock_timeout<=0 or a.timeout<=0:raise ValueError('Timeouts must be positive')
 with editor_lock(a.lock_timeout):
  result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('composa_mcp.py')),'--calls',str(a.calls),'--out',str(a.out),'--timeout',str(a.timeout)],check=False)
 raise SystemExit(result.returncode)
if __name__=='__main__':main()
