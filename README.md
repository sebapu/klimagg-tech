# klimagg-tech

> Open-source models, specifications and reference software for testing and
> implementing the Klima-Generationen-Gesetz (KlimaGG).

---

## What is klimagg-tech?

`klimagg-tech` is the technical and analytical counterpart to the
*Klima-Generationen-Gesetz* ([KlimaGG](https://klimagg.de/)). It contains two
complementary kinds of work:

1. **Models and evidence** that test policy assumptions, quantify possible
   effects and document data requirements.
2. **Specifications and reference software** for the digital infrastructure
   required to implement a KlimaGG-style law in practice.

The repository can therefore include:

- reproducible policy and market models,
- registers and journals for climate-relevant legal acts and data,
- interfaces for MRV (Monitoring, Reporting, Verification),
- a reward engine for performance-based climate payments,
- integration with transformation finance (TFK),
- state-aid classification logic (“Beihilfe-Gate”),
- indicators and APIs for traffic-light (“Ampel”) governance and dashboards,
- hooks into participation platforms and open data.

It is **not** itself a law and **not legally binding**. Models are scenarios and
reference calculations; services are reference implementations. Neither is a
normative annex to the law.

---

## Relationship to KlimaGG

The KlimaGG is a legal blueprint for:

- climate targets, budgets and paths,
- performance-based rewards,
- a transformation credit scheme (TFK),
- digital registers and once-only principles,
- monitoring and traffic-light governance,
- state-aid and fiscal frameworks.

`klimagg-tech` supports this work in two stages:

- `models/` examines whether proposed mechanisms are plausible, measurable and
  operationally definable.
- `specs/`, `services/` and `integrations/` describe and demonstrate how the
  resulting requirements could be implemented.

No deployment is required to use this exact codebase. Equivalent systems are
possible as long as they fulfil the relevant functional, security and
interoperability requirements.

---

## Current model

### Klimaleistung und EEG

[`models/klimaleistung-eeg/`](models/klimaleistung-eeg/) contains a reproducible
analysis of hourly climate performance, EEG financing data and a 2030 market
scenario. It includes:

- scripts to build and validate the required databases,
- model and analysis scripts,
- article figures and reference results,
- data-source, licence and reproducibility documentation.

The model is connected to the public background page:
[KlimaGG – Klimaleistung und EEG](https://www.klimagg.de/grundlagen/modelle-und-daten/klimaleistung-eeg/).

---

## Relation to other repositories

- **[`klimagg-law`](https://github.com/sebapu/klimagg-law)** – text and
  development history of the legal proposal.
- **[`klimagg-web`](https://github.com/sebapu/klimagg-web)** – website and
  explanatory frontend material, where available.

This repository focuses on **models, data, technical specifications, backend
logic and integration**.

---

## Goals

`klimagg-tech` aims to:

- make central assumptions of the law testable and reproducible,
- provide a coherent technical architecture for KlimaGG-style climate laws,
- re-use open-source and open-data infrastructure where responsibly possible,
- offer documented models, APIs and reference implementations,
- enable public institutions, researchers, NGOs, journalists and developers to
  inspect, reproduce and improve the work.

---

## Repository layout

This structure is a target and can grow incrementally.

```text
klimagg-tech/
  README.md
  LICENSE
  NOTICE
  models/
    README.md
    klimaleistung-eeg/
  docs/
    architecture-overview.md
    data-models/
    api/
    threat-model.md
  specs/
    registry/
    mrv/
    rewards/
    tfk/
    state-aid-gate/
    indicators/
  services/
    registry-service/
    mrv-gateway/
    rewards-service/
    indicators-service/
  integrations/
    identity-adapters/
    eo-data-examples/
    decidim-adapter/
  dev-env/
    docker-compose.yml
    k8s/
  examples/
    demo-scenarios/
    cli/
    sample-dashboards/
```

- `models/` – reproducible analytical and policy models.
- `docs/` – human-readable architecture and conceptual documentation.
- `specs/` – machine-readable specifications such as OpenAPI and JSON Schema.
- `services/` – reference implementations of core services.
- `integrations/` – adapters to external systems and data sources.
- `dev-env/` – local development and test environments.
- `examples/` – demo scenarios and example clients.

---

## Getting started

Clone the repository:

```bash
git clone https://github.com/sebapu/klimagg-tech.git
cd klimagg-tech
```

Run the currently available model:

```bash
cd models/klimaleistung-eeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The model-specific README contains the complete data and reproduction steps.
Reference services and development environments will be documented as they are
added.

---

## Contributing

Contributions are welcome, from model review and data validation to architecture
and implementation work.

- Open an issue before substantial design changes.
- Document assumptions, sources and model limits.
- Add tests or validation checks where possible.
- Avoid proprietary dependencies in core modules unless clearly isolated and
  justified.

---

## Licence

Software and specifications in this repository are licensed under the
**Apache License, Version 2.0**. This permits use, modification and
redistribution, including commercial use, subject to the licence conditions and
retention of copyright and attribution notices. See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).

Original documentation, figures and other non-software works may be released
under **CC BY 4.0** where explicitly marked. Third-party datasets remain subject
to their respective licences and attribution requirements.

---

## Legal notice

This repository:

- is not an official system of any government or public body,
- does not create legal rights or obligations by itself,
- is provided “as is”, without warranties of any kind.

Any real-world deployment must be evaluated against applicable law, security
requirements and institutional governance.
