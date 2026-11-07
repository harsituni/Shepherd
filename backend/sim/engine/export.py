"""Versioned disk contract. Manifest is the completion marker; exports never overwrite."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from rasterio.transform import Affine

from backend.sim.engine.contracts import write_b1, load_b1
from backend.sim.engine.grid import Grid
from backend.sim.engine.result import SimulationResult

MANIFEST_SCHEMA = 'shepherd.engine.export/v1'


def _json(path, value):
    path.write_text(json.dumps(value, allow_nan=False, separators=(',', ':')) + '\n')


def export_result(result, out_dir, *, minutes=None):
    if minutes is None:
        step = result.metadata['step_min']
        minutes = sorted(set(range(0, result.horizon_min + 1, step)) | {result.horizon_min})
    minutes = list(minutes)
    # Validate before creating output files.
    frames = result.frames_at(minutes)
    if result.metadata['n_ensemble'] > 1:
        frames['features'] += result.frames_at(minutes, band='p10')['features']
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = out_dir / '.export.lock'
    with lock.open('x'):
        pass
    try:
        if any(p.name not in ('scenario.json', '.export.lock') for p in out_dir.iterdir()):
            raise FileExistsError(f'{out_dir}: use a new output directory; published results are never overwritten')
        # build_live may already have written scenario.json here. Only accept the same input.
        if (out_dir / 'scenario.json').exists():
            from backend.sim.engine.contracts import load_scenario
            old = load_scenario(out_dir / 'scenario.json').model_dump(mode='json', by_alias=True)
            if old != result.scenario:
                raise FileExistsError('existing scenario.json differs from this result')
        with tempfile.TemporaryDirectory(prefix='.engine-export-', dir=out_dir.parent) as temp:
            stage = Path(temp)
            write_b1(stage, result.metadata['run_id'], result.grid,
                     result.arrival_grid(), result.arrival_grid('p10'))
            _json(stage / 'scenario.json', result.scenario)
            _json(stage / 'run_meta.json', result.metadata)
            _json(stage / 'frames.geojson', frames)
            files = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in sorted(stage.iterdir())}
            manifest = {'schema': MANIFEST_SCHEMA, 'engine_version': result.metadata['engine_version'],
                        'run_id': result.metadata['run_id'], 'metadata': 'run_meta.json',
                        'scenario': 'scenario.json', 'grid_header': 'b1_header.json',
                        'frames': 'frames.geojson', 'files': files,
                        'arrival_layers': {'p50': 'arrival_p50.npy', 'p10': 'arrival_p10.npy'},
                        'arrival_dtype': 'float32', 'nodata': 'NaN = not reached within modeled horizon',
                        'frame_minutes': minutes, 'bbox': list(result.bbox),
                        'grid_crs': 'EPSG:32612', 'geojson_crs': 'EPSG:4326',
                        'horizon_min': result.horizon_min}
            for p in stage.iterdir():
                os.replace(p, out_dir / p.name)
            _json(stage / 'manifest.json', manifest)
            os.replace(stage / 'manifest.json', out_dir / 'manifest.json')
        return manifest
    finally:
        lock.unlink()


def load_result(out_dir):
    manifest = json.loads((out_dir / 'manifest.json').read_text())
    if manifest.get('schema') != MANIFEST_SCHEMA:
        raise ValueError('unsupported export manifest schema')
    required = {'arrival_p50.npy', 'arrival_p10.npy', 'b1_header.json', 'run_meta.json', 'scenario.json', 'frames.geojson'}
    if set(manifest['files']) != required:
        raise ValueError('invalid manifest file inventory')
    for filename, entry in manifest['files'].items():
        data = (out_dir / filename).read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f'export integrity check failed: {filename}')
    meta_text = (out_dir / 'run_meta.json').read_text()
    meta = json.loads(meta_text)
    header_data = json.loads((out_dir / "b1_header.json").read_text())
    if header_data["layers"] != {'arrival_p50': 'arrival_p50.npy', 'arrival_p10': 'arrival_p10.npy'}:
        raise ValueError('invalid arrival layer paths')
    header, arrays = load_b1(out_dir)
    x, y = header.origin_xy
    grid = Grid(x, y, header.cell_m, header.rows, header.cols, Affine(header.cell_m, 0, x, 0, -header.cell_m, y))
    return SimulationResult(grid, tuple(meta['bbox']), meta['horizon_min'], arrays['arrival_p50'], arrays['arrival_p10'],
                            meta_text, (out_dir / 'scenario.json').read_text())
