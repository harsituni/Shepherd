"""Demo generator: baseline scenario (r1) + scripted wind-shift forecast update (r2).

Weather comes from the config's weather_default_source (live OpenWeather for
Edmonton) unless --source overrides it. Every live fetch is cached, so if the
network or key fails mid-demo, rerun with --source cache:latest.

    python -m backend.sim.weatherpipe.demo backend/sim/scenarios/edm-demo-1.json \
        --out contracts/ [--t0 2026-11-08T20:00:00Z] [--source cache:latest] [--run-engine]
"""

import argparse
from pathlib import Path

from backend.sim.weatherpipe.conventions import bbox_centroid, default_t0, parse_utc
from backend.sim.weatherpipe.resample import build_weather_series, coverage_metadata
from backend.sim.weatherpipe.scenario import (
    build_scenario,
    load_config,
    make_forecast_update,
    write_scenario,
)
from backend.sim.weatherpipe.shift import apply_wind_shift
from backend.sim.weatherpipe.sources import DEFAULT_CACHE_DIR, fetch_weather


def make_demo(config_path, t0, out_dir, source=None, cache_dir=DEFAULT_CACHE_DIR,
              session=None) -> tuple[Path, Path, dict, dict]:
    """Write scenario_r1.json and scenario_r2.json; return (r1_path, r2_path, r1, r2)."""
    config = load_config(config_path)
    if config.wind_shift is None:
        raise ValueError(f"{config_path}: demo needs a wind_shift block")

    lat, lon = bbox_centroid(config.bbox)
    obs, weather_source = fetch_weather(
        lat, lon, source or config.weather_default_source, t0=t0, cache_dir=cache_dir, session=session
    )
    weather = build_weather_series(obs, t0, config.horizon_min)
    weather_source.update(coverage_metadata(obs, t0, config.horizon_min))
    r1 = build_scenario(config, weather, t0, f"{config.scenario_id}-r1", weather_source)
    shifted = apply_wind_shift(r1["weather"], **config.wind_shift.model_dump())
    r2 = make_forecast_update(r1, shifted, f"{config.scenario_id}-r2", {
        **weather_source,
        "updated_from_run_id": r1["run_id"],
        "wind_shift": config.wind_shift.model_dump(),
    })
    out_dir = Path(out_dir)
    return write_scenario(r1, out_dir / "scenario_r1.json"), write_scenario(r2, out_dir / "scenario_r2.json"), r1, r2


def shift_table(r1, r2) -> str:
    lines = [
        "t_min | r1 speed m/s  dir | r2 speed m/s  dir",
        "------+-------------------+------------------",
    ]
    for a, b in zip(r1["weather"], r2["weather"]):
        mark = "" if a == b else "  <- shifted"
        lines.append(
            f"{a['t_min']:>5} | {a['wind_speed_ms']:>12.1f} {a['wind_dir_deg']:>4} "
            f"| {b['wind_speed_ms']:>12.1f} {b['wind_dir_deg']:>4}{mark}"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write baseline + wind-shift Contract A files.")
    parser.add_argument("config", type=Path, help="scenario config, e.g. backend/sim/scenarios/edm-demo-1.json")
    parser.add_argument("--t0", help="ISO 8601 UTC, default now rounded down to the hour")
    parser.add_argument("--source", help="override the config's weather source, e.g. cache:latest")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out", type=Path, default=Path("contracts"))
    parser.add_argument("--run-engine", action="store_true", help="also run the spread engine on r1 and r2")
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="engine output root")
    args = parser.parse_args(argv)

    t0 = parse_utc(args.t0) if args.t0 else default_t0()
    r1_path, r2_path, r1, r2 = make_demo(args.config, t0, args.out, args.source, args.cache_dir)
    source = r1["weather_source"]
    print(f"weather: {source['provider']} {source.get('endpoint', '')} {source.get('fetched_at', '')}".rstrip())
    print(f"wrote {r1_path}\nwrote {r2_path}\n")
    print(shift_table(r1, r2))
    if args.run_engine:
        from backend.sim.engine.run import run_engine
        for path in (r1_path, r2_path):
            result = run_engine(path, args.runs)
            print(f"engine {result['run_id']}: {result['out_dir']} ({result['elapsed_s']} s)")


if __name__ == "__main__":
    main()
