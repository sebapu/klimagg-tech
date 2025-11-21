# klimagg-tech

> Open-source backbone for implementing the Klima Generations Act (KlimaGG) –  
> a modular, reusable digital infrastructure for climate governance.

---

## What is klimagg-tech?

`klimagg-tech` is a **reference architecture and open-source toolkit** for the
digital infrastructure that a law like the *Klima-Generationen-Gesetz* (KlimaGG)
needs in order to work in practice:

- registers and journals for climate-relevant legal acts and data,
- interfaces for MRV (Monitoring, Reporting, Verification),
- a reward engine for performance-based climate payments,
- integration with transformation finance (TFK),
- state-aid classification logic (“Beihilfe-Gate”),
- indicators and APIs for traffic-light (“Ampel”) governance and dashboards,
- hooks into participation platforms and open data.

It is **not** itself a law and **not legally binding**.

It is a concrete, running answer to the question:

> *“What kind of digital infrastructure must exist so that a modern climate law
>  cannot be dismissed as ‘technically impossible’?”*

Any state, region or organisation can re-use the concepts, APIs and reference
implementations – with or without the KlimaGG itself.

---

## Relationship to KlimaGG (the law)

The *Klima-Generationen-Gesetz* (KlimaGG) is a **legal blueprint** for:

- climate targets, budgets and paths,
- performance-based rewards (Carbon Rewards),
- a transformation credit scheme (TFK),
- digital registers and once-only principles,
- monitoring and “traffic light” governance,
- state-aid and fiscal frameworks.

`klimagg-tech` is the **technical counterpart**:

- It models the **modules** the law implicitly requires.
- It offers **APIs, data models and reference services**.
- It is designed so that **no single implementation is mandatory**:
  other stacks are allowed, as long as they fulfil the same functional,
  security and interoperability requirements.

Legally, this repository is a **reference implementation**, not a normative
annex. No law may require the use of this exact codebase; it only requires that
certain functions and guarantees are provided.

---

## Relation to other repositories

- **[`klimagg-law`](https://github.com/<ORG>/klimagg-law)**  
  Text of the Klima Generations Act and its development history (CC0 1.0).

- **[`klimagg-web`](https://github.com/<ORG>/klimagg-web)**  
  Website and frontend assets explaining KlimaGG and showcasing tools built on
  top of this backbone (private at this stage).

This repo focuses on the **backend, data and integration layer**.

---

## Goals

`klimagg-tech` aims to:

- Provide a **coherent technical architecture** for KlimaGG-style climate laws.
- Re-use as much **existing open-source and open-data infrastructure** as
  responsibly possible.
- Offer **clean, documented APIs** for:
  - climate registers,
  - MRV pipelines,
  - rewards and finance,
  - governance indicators and dashboards.
- Make it easy for:
  - governments and public IT providers to deploy a working system,
  - civic-tech communities to extend and adapt it,
  - researchers to analyse data and policies,
  - NGOs and journalists to scrutinise and explain what happens.

---

## High-level architecture

`klimagg-tech` is organised into several layers/modules:

### 1. Core Registry & Journal

- Immutable, signed event store for:
  - projects and project life-cycle events,
  - MRV submissions and verification results,
  - reward series and status changes,
  - TFK contracts and updates,
  - state-aid classification events,
  - governance events (e.g. changes in methods, parameters).
- Integrates with eIDAS-compatible identity and signature solutions where
  required by law.
- Provides APIs for appending events, querying views and exporting data.

### 2. Actor & Account Layer

- Models:
  - states, regions, municipalities,
  - companies, facilities, clusters,
  - projects and portfolios.
- Supports **nested accounting** (e.g. municipality → region → state).
- Conceptually compatible with actor/target models such as OpenClimate, adapted
  to national legal identifiers and registry needs.

### 3. MRV Integration Layer

- Standard APIs to ingest:
  - measurement data,
  - activity data,
  - verification/audit outputs.
- Manages:
  - methods and factors,
  - method versions,
  - assurance levels (e.g. AL-1 / AL-2 / AL-3).
- Provides plug-in interfaces for **sectoral MRV modules**:
  - land use / forestry / agriculture,
  - energy & buildings,
  - industry & clusters,
  - transport, etc.
- Supports integration with external toolchains and open MRV tooling.

### 4. Reward Engine (Carbon Rewards)

- Converts verified emission reductions/removals into **reward units**.
- Manages:
  - reward series,
  - statuses (pending, locked, redeemed, reversed),
  - caps and floors in line with fiscal rules.
- Exposes stable APIs that financial systems can use to:
  - value rewards,
  - book rewards,
  - link rewards to payment systems (SEPA, treasury, other rails).

> The reward engine does **not** itself operate payment rails; it provides
> accounting and entitlement logic.

### 5. Transformation Credit (TFK) Integration

- Represents TFK loans and related contracts:
  - loan conditions, collateral, ranks,
  - linkage to specific projects or portfolios.
- Links TFK projects to MRV and reward flows:
  - a share of reward streams can be assigned to loan repayment,
  - expected reward flows can be used in risk assessments.
- Provides aggregate data for:
  - the climate investment window,
  - fiscal monitoring and “finance Ampel”.

### 6. State Aid (“Beihilfe”) Gate

- Implements a rule layer to classify projects/series into categories such as:
  - non-aid,
  - GBER/de-minimis compatible,
  - notified / pilot-corridor.
- Tracks:
  - status of notifications,
  - relevant constraints (caps, time limits, conditions).
- Exposes this status to:
  - reward engine (e.g. redeem-locks),
  - TFK module,
  - indicators & dashboards.

### 7. Indicators & Ampel-API

- Computes key governance indicators, e.g.:
  - emissions vs. budget,
  - budget depletion and remaining headroom,
  - MRV integrity indicators,
  - financial exposure vs. caps and buffers,
  - sectoral and regional implementation progress.
- Maps indicators to traffic-light states (green / yellow / red) based on
  threshold rules aligned with KlimaGG provisions.
- Publishes **machine-readable feeds** for:
  - dashboards,
  - parliamentary reporting,
  - public transparency.

### 8. Participation & Governance Integration

- Provides integration patterns with participation platforms (e.g. Decidim):
  - consultation of MRV methods and regulations,
  - feedback mechanisms on local projects and dashboards.
- Maps legal/technical entities (methods, programmes, projects, parameters) to
  items that citizens can see and discuss.
- Does **not** re-implement participation from scratch; it focuses on clean
  interfaces to existing platforms.

### 9. DevOps & Reference Deployment

- Containerised reference deployments (e.g. Docker Compose, Kubernetes).
- Configuration examples for:
  - dev/test environments,
  - staging and small pilot setups.
- Documentation for:
  - secrets management,
  - logging & monitoring,
  - basic security hardening.

---

## Repository layout (suggested)

This structure is a target; the project can grow into it incrementally.

```text
klimagg-tech/
  README.md
  LICENSE
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
    ...
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
````

* `docs/` – human-readable architecture and conceptual docs.
* `specs/` – machine-readable specs (OpenAPI, JSON Schema, etc.).
* `services/` – reference implementations of core services.
* `integrations/` – adapters to external systems (identity, EO data, participation).
* `dev-env/` – local dev/test environments.
* `examples/` – demo scenarios and example clients.

---

## Who is this for?

`klimagg-tech` is a toolbox for several groups:

* **Public IT organisations & ministries**
  wanting to understand what a KlimaGG-style law requires technically and how
  to implement it with open standards and open components.

* **Municipal IT & utilities**
  who need to plug in local data and use dashboards, reward flows and TFK
  integration with minimal friction.

* **Auditors, MRV providers, registries**
  who need clear, stable MRV and registry interfaces for their work.

* **Developers & civic-tech communities**
  who want to build apps, tools and extensions on top of climate-governance
  data and logic.

* **Researchers, NGOs, journalists**
  who want programmatic access to trustworthy data on climate actions, rewards,
  finances and risks.

---

## Re-use of existing projects

Where possible, `klimagg-tech` aims to **integrate or align with** existing
open-source and open-data projects, for example:

* actor/target and nested accounting initiatives (e.g. OpenClimate-like models),
* EO and climate data infrastructures (e.g. Open Earth Monitor, ESA CCI, etc.),
* participation platforms (e.g. Decidim),
* sectoral open MRV tooling (where available),
* common identity, wallet and signature solutions compliant with eIDAS.

These projects are **not required dependencies**, but preferred building blocks
where appropriate. Any deployment can pick equivalent alternatives as long as
the interfaces and guarantees defined in `klimagg-tech` are respected.

---

## Status & roadmap

> **Early design phase** – the structure and specs will evolve.

Planned milestones (subject to change):

1. **Architecture & specification skeleton**

   * initial docs for core modules and interfaces,
   * first OpenAPI & schema drafts.

2. **Minimal reference registry**

   * core journal & actor model,
   * basic MRV ingestion & reward calculation flows.

3. **Indicator & dashboard API**

   * core indicators,
   * example dashboard clients.

4. **TFK & fiscal reporting integration**

   * schemas & aggregates for climate investment window,
   * integration with reward flows.

5. **Participation & external integrations**

   * participation platform examples,
   * EO data examples,
   * state-aid rule examples.

See `docs/architecture-overview.md` (to be created) for more details.

---

## Getting started (development)

> This section will be refined as services and tooling are added.

Basic outline for local development:

```bash
git clone https://github.com/<ORG>/klimagg-tech.git
cd klimagg-tech

# Example: spin up a minimal dev environment (when available)
cd dev-env
docker compose up
```

Then:

* explore the APIs via generated docs (e.g. Swagger UI),
* run demo scenarios in `examples/` (when present),
* inspect `docs/architecture-overview.md` for conceptual guidance.

---

## Contributing

Contributions are very welcome – from architecture discussions to code.

* Please open an **issue** to discuss substantial design changes early.
* For code contributions, add tests where possible.
* Avoid introducing proprietary dependencies into core modules.

We especially welcome contributions from:

* public sector IT teams,
* MRV and registry experts,
* civic-tech communities,
* research groups working on climate governance,
* NGOs who want to use and scrutinise the data.

A `CONTRIBUTING.md` file will be added to spell out practical details.

---

## Licence

> **Suggested default:** Apache License 2.0 for code and specifications.

The code and specifications in this repository are intended to be used widely
by public institutions, NGOs, companies and individuals. For that reason, a
permissive open-source licence with a clear patent grant is preferred.

We therefore recommend licensing `klimagg-tech` under the **Apache License,
Version 2.0**.

This provides:

* broad permission to use, modify, distribute,
* an explicit patent licence,
* clear limitations of liability and warranty.

You can technically choose a different licence (e.g. CC0 1.0 or AGPL-3.0), but:

* **CC0 1.0** maximises re-use, yet:

  * does not provide an explicit patent grant,
  * is less standard for complex software stacks.
* **AGPL-3.0** enforces sharing improvements for SaaS deployments, but can make
  adoption by public bodies and vendors more difficult.

**Recommended:** keep Apache-2.0 as the default for this infrastructure project.

See [`LICENSE`](LICENSE) for the full licence text.

---

## Legal notice

This repository:

* is not an official system of any government or public body,
* does not create legal rights or obligations by itself,
* is provided “as is”, without warranties of any kind.

Any real-world deployment must be:

* evaluated against applicable law and regulations,
* security-reviewed,
* operated by competent institutions under appropriate governance.

```
::contentReference[oaicite:0]{index=0}
```
