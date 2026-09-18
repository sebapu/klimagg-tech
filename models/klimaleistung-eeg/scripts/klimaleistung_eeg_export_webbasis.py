#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Sebastian Putzke
# SPDX-License-Identifier: Apache-2.0
"""Export the canonical Klimaleistung/EEG analysis into a compact web result kernel.

The exporter contains no independent market or EEG model. It imports and calls
functions from the existing ``klimaleistung-eeg`` analysis modules, evaluates a
small documented scenario grid, and serializes the results for ``klimagg-web``.

Run from ``models/klimaleistung-eeg`` for example::

    python scripts/klimaleistung_eeg_export_webbasis.py

Explicit paths can be supplied when the derived SQLite files live elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_DIR = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = MODEL_DIR / "data" / "derived"
DEFAULT_OUTPUT = MODEL_DIR / "results" / "web" / "klimaleistung_eeg_basis.json"

SCHEMA = "klimagg.klimaleistung_eeg.webbasis.v1"
EXPORTER_VERSION = "1.0.0"
DEFAULT_DEMAND_SCALES = (0.50, 1.00, 2.00)
DEFAULT_FLOORS_EUR_T = (50.0, 74.0, 100.0, 150.0)
DEFAULT_GUARANTEE_TWH = (10.0, 25.0, 50.0, 75.0, 100.0, 125.0, 150.0)
DEFAULT_PRIVATE_SHARES = (0.25, 0.50, 1.00)
DEFAULT_EEG_PRICE_MAX = 250
DEFAULT_EEG_PRICE_STEP = 1


def _import_modules():
    # The canonical tech modules live next to this exporter. Importing them here
    # keeps all domain calculations in their existing implementations.
    import artikelgrafiken_eeg_klimaleistung as article_core
    import eeg_klimaleistung_deckungsanalyse as eeg
    import klimaleistung_marktmodell_2030 as market

    return article_core, eeg, market


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} fehlt: {path}")
    return path


def _round_list(values: np.ndarray, digits: int) -> list[float]:
    return [round(float(value), digits) for value in np.asarray(values, dtype=float)]


def _finite(value: float | int) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"Nichtendlicher Ergebniswert: {value!r}")
    return out


def _market_scenario(
    *,
    market,
    demand_scale: float,
    total_supply: np.ndarray,
    base_demand: np.ndarray,
    tranche_profiles,
    fossil_intensity: np.ndarray,
    scarcity_premium_eur_mwh: float,
    floor_values: tuple[float, ...],
    guarantee_values: tuple[float, ...],
    eeg,
    eeg_scope,
    eeg_references,
    eeg_private_shares: tuple[float, ...],
    eeg_year: int,
) -> dict[str, Any]:
    demand = np.asarray(base_demand, dtype=float) * float(demand_scale)
    clearing = market.clear_market(demand, tranche_profiles, scarcity_premium_eur_mwh)
    price_eur_mwh = np.asarray(clearing["price_eur_mwh"], dtype=float)
    accepted_mwh = np.asarray(clearing["accepted_mwh"], dtype=float)
    shortage_mwh = np.asarray(clearing["shortage_mwh"], dtype=float)
    price_eur_t = np.divide(
        price_eur_mwh,
        fossil_intensity,
        out=np.zeros_like(price_eur_mwh, dtype=float),
        where=fossil_intensity > 0,
    )

    shortage_mask = shortage_mwh > 1e-9
    known_mask = ~shortage_mask
    known_prices = price_eur_t[known_mask]
    known_weights = accepted_mwh[known_mask]
    weighted_price_eur_mwh = (
        float(np.sum(price_eur_mwh[known_mask] * known_weights) / np.sum(known_weights))
        if np.sum(known_weights) > 0
        else 0.0
    )
    weighted_price_eur_t = (
        float(np.sum(known_prices * known_weights) / np.sum(known_weights))
        if np.sum(known_weights) > 0
        else 0.0
    )

    shortage_hours = int(np.count_nonzero(shortage_mask))
    net_balance = np.asarray(total_supply, dtype=float) - demand
    balance_order = np.argsort(net_balance)
    sorted_supply_gw = np.asarray(total_supply, dtype=float)[balance_order] / 1000.0
    sorted_demand_gw = demand[balance_order] / 1000.0
    sorted_balance_gw = net_balance[balance_order] / 1000.0

    # Keep shortage hours explicit and separate from the price curve. The tech
    # model deliberately does not call its scarcity sensitivity a market price.
    price_duration = [None] * shortage_hours + _round_list(np.sort(known_prices)[::-1], 3)

    guarantees: dict[str, Any] = {}
    for floor in floor_values:
        floor_mwh = float(floor) * fossil_intensity
        by_volume: dict[str, Any] = {}
        for volume in guarantee_values:
            result = market.guarantee_for_pilot(
                float(volume),
                np.asarray(total_supply, dtype=float),
                demand,
                price_eur_mwh,
                floor_mwh,
            )
            by_volume[f"{volume:g}"] = {
                key: (int(value) if key == "state_purchase_hours" else round(float(value), 6))
                for key, value in result.items()
            }
        guarantees[f"{floor:g}"] = by_volume

    eeg_reference_by_private_share: dict[str, Any] = {}
    for share in eeg_private_shares:
        total, _ = eeg.aggregate_for_price(
            eeg_scope,
            eeg_references,
            weighted_price_eur_t,
            float(share),
            eeg_year,
        )
        eeg_reference_by_private_share[f"{share:g}"] = {
            "climate_price_eur_t": round(weighted_price_eur_t, 6),
            "private_share": float(share),
            "funding_gap_replaced_billion_eur": round(total.climate_support_relief_eur / 1e9, 6),
            "remaining_support_billion_eur": round(
                (total.support_requirement_eur - total.climate_support_relief_eur) / 1e9,
                6,
            ),
            "funding_gap_replaced_share": round(
                total.climate_support_relief_eur / total.support_requirement_eur
                if total.support_requirement_eur
                else 0.0,
                8,
            ),
        }

    return {
        "demand_scale": float(demand_scale),
        "summary": {
            "renewable_supply_twh": round(float(np.sum(total_supply)) / 1e6, 6),
            "strict_demand_twh": round(float(np.sum(demand)) / 1e6, 6),
            "shortage_hours": shortage_hours,
            "shortage_twh": round(float(np.sum(shortage_mwh)) / 1e6, 6),
            "max_hourly_shortage_gw": round(float(np.max(shortage_mwh)) / 1000.0, 6),
            "surplus_twh": round(float(np.sum(np.maximum(net_balance, 0.0))) / 1e6, 6),
            "weighted_offer_floor_eur_mwh": round(weighted_price_eur_mwh, 6),
            "weighted_climate_price_eur_t": round(weighted_price_eur_t, 6),
            "price_not_determinable_hours": shortage_hours,
        },
        "price_duration": {
            "x_hours": list(range(1, len(price_duration) + 1)),
            "price_eur_t": price_duration,
            "shortage_hours": shortage_hours,
        },
        "balance_duration": {
            "x_hours": list(range(1, len(sorted_balance_gw) + 1)),
            "supply_gw": _round_list(sorted_supply_gw, 4),
            "demand_gw": _round_list(sorted_demand_gw, 4),
            "balance_gw": _round_list(sorted_balance_gw, 4),
        },
        "guarantees": guarantees,
        "eeg_reference_2024_by_private_share": eeg_reference_by_private_share,
    }


def _build_eeg_basis(
    *,
    eeg,
    article_core,
    smard_db: Path,
    eeg_db: Path,
    year: int,
    price_max: int,
    price_step: int,
    private_shares: tuple[float, ...],
) -> tuple[dict[str, Any], Any, Any]:
    categories, db_info = eeg.load_categories(eeg_db, year)
    references = eeg.references_from_core(article_core, smard_db, year)
    scope_info = eeg.scope_summary(categories, references, year)
    scope = scope_info["scope"]
    support_base = float(scope_info["support_requirement_eur"])
    scope_payment = float(scope_info["positive_payment_eur"])

    curves: dict[str, list[dict[str, float]]] = {}
    for share in private_shares:
        points: list[dict[str, float]] = []
        for price in range(0, int(price_max) + 1, int(price_step)):
            total, _ = eeg.aggregate_for_price(scope, references, float(price), float(share), year)
            points.append(
                {
                    "price_eur_t": float(price),
                    "eeg_payment_covered_billion_eur": round(total.operator_payment_covered_eur / 1e9, 6),
                    "eeg_payment_covered_share": round(
                        total.operator_payment_covered_eur / scope_payment if scope_payment else 0.0,
                        8,
                    ),
                    "funding_gap_replaced_billion_eur": round(total.climate_support_relief_eur / 1e9, 6),
                    "funding_gap_replaced_share": round(
                        total.climate_support_relief_eur / support_base if support_base else 0.0,
                        8,
                    ),
                    "remaining_support_billion_eur": round(
                        (support_base - total.climate_support_relief_eur) / 1e9,
                        6,
                    ),
                }
            )
        curves[f"{share:g}"] = points

    carrier_reference = []
    for carrier in eeg.CARRIER_ORDER:
        ref = references[carrier]
        carrier_reference.append(
            {
                "carrier": carrier,
                "yield_mwh_per_mw": round(float(ref.energy_mwh_per_mw), 6),
                "market_value_eur_mwh": round(float(ref.market_value_eur_mwh), 6),
                "climate_t_co2e_mwh": round(float(ref.climate_t_mwh), 8),
            }
        )

    basis = {
        "year": int(year),
        "summary": {
            "positive_payments_model_scope_billion_eur": round(scope_payment / 1e9, 6),
            "funding_gap_after_market_value_billion_eur": round(support_base / 1e9, 6),
            "modeled_electricity_twh": round(float(scope_info["positive_quantity_kwh"]) / 1e9, 6),
            "database_net_payment_billion_eur": round(float(db_info["raw_net_payment_eur"]) / 1e9, 6),
        },
        "private_shares": [float(value) for value in private_shares],
        "price_grid": {
            "min_eur_t": 0,
            "max_eur_t": int(price_max),
            "step_eur_t": int(price_step),
        },
        "curves": curves,
        "carrier_reference": carrier_reference,
    }
    return basis, scope, references


def build_web_basis(args: argparse.Namespace) -> dict[str, Any]:
    article_core, eeg, market = _import_modules()

    smard_db = _require_file(args.smard_db, "SMARD-Datenbank")
    eeg_db = _require_file(args.eeg_db, "EEG-Datenbank")
    weather_db = _require_file(args.weather_db, "Wetter-/Szenariendatenbank")
    core_script = _require_file(SCRIPT_DIR / "artikelgrafiken_eeg_klimaleistung.py", "Artikelgrafik-Kern")
    market_script = _require_file(SCRIPT_DIR / "klimaleistung_marktmodell_2030.py", "Marktmodell")
    eeg_script = _require_file(SCRIPT_DIR / "eeg_klimaleistung_deckungsanalyse.py", "EEG-Deckungsanalyse")

    eeg_basis, eeg_scope, eeg_references = _build_eeg_basis(
        eeg=eeg,
        article_core=article_core,
        smard_db=smard_db,
        eeg_db=eeg_db,
        year=int(args.eeg_year),
        price_max=int(args.eeg_price_max),
        price_step=int(args.eeg_price_step),
        private_shares=tuple(args.private_shares),
    )

    inputs = market.load_hourly_inputs(
        smard_db,
        weather_db,
        int(args.weather_year),
        str(args.weather_site),
    )
    supply = market.build_supply(inputs)
    strict_demand = market.build_strict_demand(inputs)
    district_heat = market.build_district_heat_hp(inputs)
    fossil_intensity = np.asarray(market.build_fossil_intensity(inputs), dtype=float)

    total_supply = np.sum(np.vstack(list(supply.values())), axis=0)
    demand_without_heat = np.sum(np.vstack(list(strict_demand.values())), axis=0)
    hp_electricity = np.asarray(district_heat["hp_electricity_mwh"], dtype=float)
    base_demand = demand_without_heat + hp_electricity
    tranches = market.offer_tranches()
    tranche_profiles = market.build_tranche_profiles(supply, tranches)

    market_scenarios: dict[str, Any] = {}
    for scale in args.demand_scales:
        market_scenarios[f"{scale:g}"] = _market_scenario(
            market=market,
            demand_scale=float(scale),
            total_supply=total_supply,
            base_demand=base_demand,
            tranche_profiles=tranche_profiles,
            fossil_intensity=fossil_intensity,
            scarcity_premium_eur_mwh=float(args.scarcity_premium_eur_mwh),
            floor_values=tuple(args.floors_eur_t),
            guarantee_values=tuple(args.guarantee_twh),
            eeg=eeg,
            eeg_scope=eeg_scope,
            eeg_references=eeg_references,
            eeg_private_shares=tuple(args.private_shares),
            eeg_year=int(args.eeg_year),
        )

    source_files = {
        "smard_db": smard_db,
        "eeg_db": eeg_db,
        "weather_db": weather_db,
        "article_core": core_script,
        "market_model": market_script,
        "eeg_analysis": eeg_script,
    }

    return {
        "schema": SCHEMA,
        "model": "klimaleistung_eeg",
        "basis_status": "complete",
        "exporter_version": EXPORTER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "repository": "https://github.com/sebapu/klimagg-tech/tree/main/models/klimaleistung-eeg",
            "market_model_version": str(getattr(market, "MODEL_VERSION", "unknown")),
            "eeg_analysis_version": str(getattr(eeg, "VERSION", "unknown")),
            "article_core_version": str(getattr(article_core, "VERSION", "unknown")),
            "model_year": int(getattr(market, "MODEL_YEAR", 2030)),
            "weather_profile_year": int(args.weather_year),
            "weather_site": str(args.weather_site),
            "eeg_reference_year": int(args.eeg_year),
            "files": {
                name: {"path": str(path), "sha256": _sha256(path)}
                for name, path in source_files.items()
            },
        },
        "controls": {
            "demand_scales": [float(value) for value in args.demand_scales],
            "state_floors_eur_t": [float(value) for value in args.floors_eur_t],
            "guarantee_volumes_twh": [float(value) for value in args.guarantee_twh],
            "eeg_private_shares": [float(value) for value in args.private_shares],
            "defaults": {
                "demand_scale": 1.0,
                "state_floor_eur_t": 74.0,
                "guarantee_volume_twh": 50.0,
                "eeg_private_share": 1.0,
            },
        },
        "market": {
            "available": True,
            "model_year": int(getattr(market, "MODEL_YEAR", 2030)),
            "base_demand_twh": round(float(np.sum(base_demand)) / 1e6, 6),
            "renewable_supply_twh": round(float(np.sum(total_supply)) / 1e6, 6),
            "demand_groups_twh": {
                **{key: round(float(np.sum(values)) / 1e6, 6) for key, values in strict_demand.items()},
                "district_heat_hp": round(float(np.sum(hp_electricity)) / 1e6, 6),
            },
            "offer_tranches": [
                {
                    "technology": tranche.technology,
                    "label": tranche.label,
                    "annual_gwh": round(float(tranche.annual_gwh), 6),
                    "offer_eur_mwh": round(float(tranche.offer_eur_mwh), 6),
                }
                for tranche in sorted(tranches, key=lambda item: item.offer_eur_mwh)
            ],
            "scenarios": market_scenarios,
        },
        "eeg": eeg_basis,
        "contract": {
            "schema": "klimagg.model-run.v1",
            "producer": "klimaleistung_eeg",
            "downstream": ["strompreis"],
            "note": (
                "The web model publishes explicit results for downstream models. "
                "No downstream model reads this basis file or the tech SQLite databases directly."
            ),
        },
    }


def _float_list(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in str(text).split(",") if part.strip())
    if not values or any(not math.isfinite(value) for value in values):
        raise argparse.ArgumentTypeError("Erwartet wird eine kommagetrennte Liste endlicher Zahlen.")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smard-db", type=Path, default=DEFAULT_DATA_DIR / "smard_stundendaten_2021_2025.sqlite")
    parser.add_argument("--eeg-db", type=Path, default=DEFAULT_DATA_DIR / "netztransparenz_eeg.sqlite")
    parser.add_argument("--weather-db", type=Path, default=DEFAULT_DATA_DIR / "wetterdaten_szenarien.sqlite")
    parser.add_argument("--weather-year", type=int, default=2024)
    parser.add_argument("--weather-site", default="kassel_51.3127_9.4797_167")
    parser.add_argument("--eeg-year", type=int, default=2024)
    parser.add_argument("--demand-scales", type=_float_list, default=DEFAULT_DEMAND_SCALES)
    parser.add_argument("--floors-eur-t", type=_float_list, default=DEFAULT_FLOORS_EUR_T)
    parser.add_argument("--guarantee-twh", type=_float_list, default=DEFAULT_GUARANTEE_TWH)
    parser.add_argument("--private-shares", type=_float_list, default=DEFAULT_PRIVATE_SHARES)
    parser.add_argument("--eeg-price-max", type=int, default=DEFAULT_EEG_PRICE_MAX)
    parser.add_argument("--eeg-price-step", type=int, default=DEFAULT_EEG_PRICE_STEP)
    parser.add_argument(
        "--scarcity-premium-eur-mwh",
        type=float,
        default=200.0,
        help="Existing tech-model sensitivity used only in guarantee calculations, not shown as a market price.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.eeg_price_step <= 0 or args.eeg_price_max < 0:
        raise SystemExit("EEG-Preisraster muss einen positiven Schritt und ein nichtnegatives Maximum haben.")
    basis = build_web_basis(args)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(basis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
