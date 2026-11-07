"""Compatibility CLI/export wrapper around the public standalone engine."""
import argparse
import json
import time
from pathlib import Path

from backend.sim.engine.contracts import load_scenario
from backend.sim.engine.simulation import ENGINE_VERSION, ASSUMPTIONS, _compute, run_simulation


def run_engine(scenario, out_root=Path('runs'), *, mock=False, cell_m=None):
    started = time.perf_counter()
    sc = load_scenario(scenario)
    if cell_m is not None:
        data = sc.model_dump(mode='json', by_alias=True)
        data['cell_m'] = cell_m
        sc = load_scenario(data)
    result = _compute(sc, mock=True) if mock else run_simulation(sc)
    out = Path(out_root) / sc.run_id
    result.export(out)
    return {'run_id': sc.run_id, 'out_dir': str(out), 'b1_header_path': str(out / 'b1_header.json'),
            'frames_path': str(out / 'frames.geojson'), 'manifest_path': str(out / 'manifest.json'),
            'elapsed_s': round(time.perf_counter() - started, 3)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Standalone forecast-driven FBP engine')
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--out', type=Path, default=Path('runs'))
    parser.add_argument('--cell-m', type=int, default=None)
    parser.add_argument('--mock', action='store_true', help='legacy analytic fixture mode; NOT FBP')
    args = parser.parse_args(argv)
    print(json.dumps(run_engine(args.scenario, args.out, mock=args.mock, cell_m=args.cell_m), indent=2))

if __name__ == '__main__':
    main()
