"""Canadian Forest Fire Behavior Prediction (FBP) System equations for M-1 / M-2 fuels.

Pure functions with no grid logic. Every function accepts floats or numpy arrays.
Wind speed WS is the 10 m open wind in km/h (slope is 0, so it is also the net
effective wind speed). Rates of spread are in m/min.

Sources:
    Forestry Canada Fire Danger Group (1992). Development and Structure of the
    Canadian Forest Fire Behavior Prediction System. Information Report ST-X-3.

    Wotton, B.M., Alexander, M.E., Taylor, S.W. (2009). Updates and Revisions to
    the 1992 Canadian Forest Fire Behavior Prediction System. Information Report
    GLC-X-10.

Crown fraction burned and foliar moisture content are not modelled: for M-1/M-2
the published ROS curves already reflect observed crowning.
"""

from typing import NamedTuple

import numpy as np

FUEL_TYPES = ("M-1", "M-2")
MIXEDWOOD_Q = 0.8
MIXEDWOOD_BUI0 = 50
# Share of the D-1 (leafless aspen) rate kept in each mixedwood type.
D1_WEIGHT = {"M-1": 1.0, "M-2": 0.2}


class SpreadRates(NamedTuple):
    ros: np.ndarray   # head fire rate of spread, m/min
    bros: np.ndarray  # back fire rate of spread, m/min
    fros: np.ndarray  # flank fire rate of spread, m/min
    lb: np.ndarray    # length-to-breadth ratio


def _scalar(x):
    """Return numpy 0-d results as plain numpy scalars."""
    return np.asarray(x)[()]


def ffmc_to_moisture(ffmc):
    """Fine fuel moisture content (%) from FFMC."""
    return 147.27723 * (101 - ffmc) / (59.5 + ffmc)


def fine_fuel_moisture_function(m):
    return 91.9 * np.exp(-0.1386 * m) * (1 + m**5.31 / 4.93e7)


def wind_function(ws_kmh):
    ws = np.asarray(ws_kmh, dtype=float)
    low = np.exp(0.05039 * ws)
    high = 12 * (1 - np.exp(-0.0818 * (ws - 28)))
    return _scalar(np.where(ws <= 40, low, high))


def isi(ffmc, ws_kmh):
    """Initial Spread Index."""
    return 0.208 * wind_function(ws_kmh) * fine_fuel_moisture_function(ffmc_to_moisture(ffmc))


def back_isi(ffmc, ws_kmh):
    """ISI with the back-wind function, for the back fire."""
    return 0.208 * np.exp(-0.05039 * ws_kmh) * fine_fuel_moisture_function(ffmc_to_moisture(ffmc))


def rsi_c2(isi_value):
    return 110 * (1 - np.exp(-0.0282 * isi_value)) ** 1.5


def rsi_d1(isi_value):
    return 30 * (1 - np.exp(-0.0232 * isi_value)) ** 1.6


def rsi_mixedwood(isi_value, fuel_type, pc):
    """Initial rate of spread for M-1 / M-2 with pc percent conifer."""
    if fuel_type not in D1_WEIGHT:
        raise ValueError(f"unsupported fuel_type {fuel_type!r}, expected one of {FUEL_TYPES}")
    conifer = pc / 100
    return conifer * rsi_c2(isi_value) + D1_WEIGHT[fuel_type] * (1 - conifer) * rsi_d1(isi_value)


def buildup_effect(bui, q=MIXEDWOOD_Q, bui0=MIXEDWOOD_BUI0):
    bui = np.asarray(bui, dtype=float)
    with np.errstate(divide="ignore"):
        be = np.exp(50 * np.log(q) * (1 / bui - 1 / bui0))
    return _scalar(np.where(bui > 0, be, 0.0))


def ros(fuel_type, pc, ffmc, bui, ws_kmh):
    """Head fire rate of spread, m/min."""
    return rsi_mixedwood(isi(ffmc, ws_kmh), fuel_type, pc) * buildup_effect(bui)


def back_ros(fuel_type, pc, ffmc, bui, ws_kmh):
    """Back fire rate of spread, m/min."""
    return rsi_mixedwood(back_isi(ffmc, ws_kmh), fuel_type, pc) * buildup_effect(bui)


def length_to_breadth(ws_kmh):
    """Length-to-breadth ratio for non-grass fuels."""
    return 1.0 + 8.729 * (1 - np.exp(-0.030 * ws_kmh)) ** 2.155


def flank_ros(ros_value, bros_value, lb):
    return (ros_value + bros_value) / (2 * lb)


def spread_rates(fuel_type, pc, ffmc, bui, ws_kmh) -> SpreadRates:
    head = ros(fuel_type, pc, ffmc, bui, ws_kmh)
    back = back_ros(fuel_type, pc, ffmc, bui, ws_kmh)
    lb = length_to_breadth(ws_kmh)
    return SpreadRates(head, back, flank_ros(head, back, lb), lb)


def directional_ros(ros_value, bros_value, fros_value, theta):
    """Spread rate (m/min) along a ray at theta radians from the head direction.

    Shifted ellipse matching head, back and flank rates (ignition is not generally a focus): a = (ROS + BROS)/2,
    b = FROS, c = (ROS - BROS)/2, and r(theta) is the positive root of
    (r cos(theta) - c)^2 / a^2 + (r sin(theta))^2 / b^2 = 1.
    Returns 0 where every rate is 0 (e.g. BUI = 0).
    """
    a = (ros_value + bros_value) / 2
    b = fros_value
    c = (ros_value - bros_value) / 2
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    with np.errstate(divide="ignore", invalid="ignore"):
        qa = cos_t**2 / a**2 + sin_t**2 / b**2
        qb = -2 * c * cos_t / a**2
        qc = c**2 / a**2 - 1
        r = (-qb + np.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
    return _scalar(np.where((a > 0) & (b > 0), r, 0.0))
