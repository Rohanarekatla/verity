/**
 * contract-check.ts — compile-time proof that the worker's hand-written
 * boundary interfaces conform to the generated contract (A6.3).
 *
 * The drift test on the Python side (test_contract_drift.py) guarantees
 * contract-types.ts matches the Pydantic models. This file closes the last
 * gap: that the interfaces the worker actually builds and returns conform to
 * that contract. If a worker interface drifts — a renamed field, a wrong type
 * — `tsc` fails here, which is the Week-2 `element_screenshots` drift turned
 * into a red build instead of a thing caught by reading code by hand.
 *
 * Scope note: this asserts the payloads whose worker types live on `main`
 * today — the contrast sampler (`sampling.ts`, A3.x). The keyboard payloads
 * (`TabStop`, `TraversalResult`, `UnreachedRegion` in `interaction/traverse.ts`)
 * are generated in the mirror already — the Python models exist — but their
 * worker types land with Week 4 (A4.x). The conformance assertions for them are
 * added in that change, where `traverse.ts` is present to import.
 *
 * Nothing here runs. The assertions are types; the `const … = true` lines are
 * the mechanism — when a `Conforms<…>` resolves to `never`, `true` is no longer
 * assignable to it and the compile fails.
 */

import type * as Contract from "./contract-types.js";
import type {
  RegionSample as WorkerRegionSample,
  Rgb as WorkerRgb,
  BackgroundSample as WorkerBackgroundSample,
} from "../static/sampling.js";

// A value of the worker type must be assignable to the contract type: whatever
// the worker returns across the RPC boundary is a valid instance of the shared
// contract. Resolves to `never` when it is not — which makes the line below
// fail to compile.
type Conforms<Worker, Spec> = Worker extends Spec ? true : never;

const _regionSample: Conforms<WorkerRegionSample, Contract.RegionSample> = true;
const _rgb: Conforms<WorkerRgb, Contract.Rgb> = true;
const _backgroundSample: Conforms<WorkerBackgroundSample, Contract.BackgroundSample> = true;

// Mark as used so the checks survive a noUnusedLocals pass without being the
// point of the file.
void _regionSample;
void _rgb;
void _backgroundSample;
