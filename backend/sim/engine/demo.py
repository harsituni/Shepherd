"""One-command offline FBP demonstration; also a runnable Python usage example."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from backend.sim.engine import run_simulation
from backend.sim.weatherpipe.resample import build_weather_series, coverage_metadata
from backend.sim.weatherpipe.scenario import load_config, build_scenario, next_run_id
from backend.sim.weatherpipe.sources import fetch_weather

SCENARIOS = Path(__file__).resolve().parents[1] / 'scenarios'


def demo_scenario():
    config=load_config(SCENARIOS/'edm-demo-1.json')
    t0=datetime(2026,11,8,20,tzinfo=timezone.utc)
    obs,source=fetch_weather(53.5,-113.565,f'canned:{SCENARIOS / "edm-demo-1.weather.json"}',t0=t0)
    source.update(coverage_metadata(obs,t0,config.horizon_min))
    weather=build_weather_series(obs,t0,config.horizon_min)
    return build_scenario(config,weather,t0,'edm-offline-r1',source)


def demonstrate(out_dir):
    result=run_simulation(demo_scenario())
    result.export(out_dir)
    queries={
        'ignition':asdict(result.arrival_at(53.535,-113.663,minute=180)),
        'east':asdict(result.arrival_at(53.535,-113.64,minute=180)),
        'far_corner':asdict(result.arrival_at(53.421,-113.699,minute=180)),
        'outside':asdict(result.arrival_at(53.3,-113.5,minute=180)),
    }
    return {'out_dir':str(out_dir),'manifest':str(Path(out_dir)/'manifest.json'),
            'grid':[result.grid.rows,result.grid.cols], 'cells_reached':result.metadata['cells_reached_p50'],
            'queries':queries}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=None,help='new output directory; defaults to a fresh offline-demo-rN directory')
    args=parser.parse_args(argv)
    root = SCENARIOS.parent / 'runs'
    out = args.out or root / next_run_id('offline-demo', root)
    print(json.dumps(demonstrate(out),indent=2))

if __name__=='__main__':main()
