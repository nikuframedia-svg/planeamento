"""Measure SQL bottlenecks during isolated macro revisions, without parameters."""
import hashlib,json,threading,time
from collections import defaultdict
import psycopg
from scripts.planning_v06_context import run,F
from app.raw import worker


def main():
    stats=defaultdict(lambda:{'calls':0,'seconds':0.0});lock=threading.Lock()
    original=psycopg.Cursor.execute
    def timed(cursor,query,*args,**kwargs):
        start=time.monotonic()
        try:return original(cursor,query,*args,**kwargs)
        finally:
            elapsed=time.monotonic()-start;statement=str(query)
            with lock:
                row=stats[(threading.current_thread().name,statement)];row['calls']+=1;row['seconds']+=elapsed
    psycopg.Cursor.execute=timed;report=[]
    try:
        for action in ['macro_close','macro_open']:
            change=run(action,'cantoneiras',None);stats.clear();start=time.monotonic();success=worker.refresh_sources()
            queries=[{'thread':key[0],'query':key[1][:1600],**value} for key,value in stats.items()]
            queries.sort(key=lambda r:-r['seconds'])
            item={'action':action,'seconds':time.monotonic()-start,'success':success,'queries':queries,'source':change['result']}
            report.append(item);(F/'t10-recalc-sql-profile.json').write_text(json.dumps(report,indent=2)+'\n')
            print(action,item['seconds'],success,flush=True)
    finally:psycopg.Cursor.execute=original


if __name__=='__main__':main()
