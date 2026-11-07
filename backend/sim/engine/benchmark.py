"""Benchmark in fresh subprocesses so peak RSS is measured per configuration."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from backend.sim.engine import run_simulation
from backend.sim.engine.demo import demo_scenario


def measure(cell_m,ensemble,out):
    scenario=demo_scenario()
    scenario.update(cell_m=cell_m,n_ensemble=ensemble,run_id=f'bench-{cell_m}m-{ensemble}members')
    start=time.perf_counter();result=run_simulation(scenario);simulation=time.perf_counter()-start
    minutes=list(range(0,result.horizon_min+1,15))
    start=time.perf_counter();result.frames_at(minutes);perimeters=time.perf_counter()-start
    start=time.perf_counter();result.export(out);export=time.perf_counter()-start
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes=peak if sys.platform=='darwin' else peak*1024
    return {'cell_m':cell_m,'rows':result.grid.rows,'cols':result.grid.cols,
            'horizon_min':result.horizon_min,'forecast_steps':len(scenario['weather']),
            'integration_step_min':scenario['integration_step_min'],'ensemble_members':ensemble,
            'simulation_s':round(simulation,4),'perimeter_s':round(perimeters,4),
            'export_s_including_frames':round(export,4),'peak_rss_mib':round(peak_bytes/2**20,2),
            'files_bytes':{p.name:p.stat().st_size for p in sorted(out.iterdir()) if p.is_file()},
            'total_output_bytes':sum(p.stat().st_size for p in out.iterdir() if p.is_file()),
            'reached_cells':result.metadata['cells_reached_p50']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--cell-m',type=int,default=100)
    parser.add_argument('--ensemble',type=int,default=1)
    args=parser.parse_args(argv)
    if args.worker:
        print(json.dumps(measure(args.cell_m,args.ensemble,args.out)))
        return
    args.out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for cell,members in [(100,1),(50,1),(25,1),(100,5)]:
        command=[sys.executable,'-m','backend.sim.engine.benchmark','--worker','--cell-m',str(cell),
                 '--ensemble',str(members),'--out',str(args.out/f'{cell}m-{members}members')]
        row=json.loads(subprocess.check_output(command,text=True))
        rows.append(row); print(json.dumps(row),flush=True)
    (args.out/'benchmarks.json').write_text(json.dumps({'python':sys.version,'platform':sys.platform,'results':rows},indent=2)+'\n')

if __name__=='__main__':main()
