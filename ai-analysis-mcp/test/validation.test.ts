import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  computeEngineHealth,
  isRejection,
  validateContentGrounding,
  validateGrounding,
} from "../dist/validation.js";

describe("validateGrounding", () => {
  it("accepts refs that are a subset of what was provided", () => {
    assert.equal(validateGrounding(["a"], ["a", "b"], false), "grounded");
  });

  it("rejects a firm conclusion citing nothing", () => {
    assert.equal(validateGrounding([], ["a"], false), "rejected_no_evidence");
  });

  it("rejects an invented evidence id", () => {
    assert.equal(validateGrounding(["zz"], ["a"], false), "rejected_ungrounded");
  });

  it("accepts an honest insufficient-evidence answer with no refs", () => {
    assert.equal(validateGrounding([], ["a"], true), "grounded");
  });

  it("rejects an invented id even when insufficient_evidence is set", () => {
    // Returning early on the flag let a hallucinated id through to the
    // caller and into the audit log as grounded.
    assert.equal(
      validateGrounding(["EV-9999"], ["EV-1"], true), "rejected_ungrounded",
    );
  });
});

describe("validateContentGrounding", () => {
  it("accepts vocabulary flags with a matching method", () => {
    assert.equal(validateContentGrounding(["pii"], "content_analysis", true), "grounded");
    assert.equal(
      validateContentGrounding(["none_detected"], "subject_line_fallback", false),
      "grounded",
    );
  });

  it("rejects a content_analysis claim when no body was supplied", () => {
    assert.equal(
      validateContentGrounding(["pii"], "content_analysis", false),
      "rejected_ungrounded",
    );
  });

  it("rejects a subject_line_fallback claim when a body was supplied", () => {
    assert.equal(
      validateContentGrounding(["pii"], "subject_line_fallback", true),
      "rejected_ungrounded",
    );
  });

  it("rejects flags outside the controlled vocabulary", () => {
    assert.equal(
      validateContentGrounding(["made_up_flag"], "content_analysis", true),
      "rejected_ungrounded",
    );
  });
});

describe("computeEngineHealth", () => {
  it("reports a zero rate for an empty window", () => {
    const health = computeEngineHealth([], 20, 0.3);
    assert.equal(health.rejectionRate, 0);
    assert.equal(health.circuitBreakerTripped, false);
  });

  it("does not trip below the minimum sample size", () => {
    const health = computeEngineHealth(
      ["rejected_ungrounded", "rejected_ungrounded"], 20, 0.3,
    );
    assert.equal(health.rejectionRate, 1);
    assert.equal(health.circuitBreakerTripped, false, "2 calls is too few to trip");
  });

  it("trips once the rate exceeds the threshold over enough calls", () => {
    const health = computeEngineHealth(
      ["grounded", "grounded", "rejected_ungrounded", "rejected_no_evidence", "engine_error"],
      20, 0.3,
    );
    assert.equal(health.rejectedInWindow, 3);
    assert.equal(health.circuitBreakerTripped, true);
  });

  it("counts engine errors as rejections so an outage trips the breaker", () => {
    const health = computeEngineHealth(
      ["engine_error", "engine_error", "engine_error", "grounded", "grounded"], 20, 0.3,
    );
    assert.equal(health.rejectedInWindow, 3);
    assert.equal(health.circuitBreakerTripped, true);
  });

  it("a window smaller than the minimum sample tightens the breaker, not disables it", () => {
    // With a hardcoded minimum of 5, AI_CIRCUIT_BREAKER_WINDOW=3 meant
    // callsInWindow could never reach it — an operator tightening the window
    // silently turned the breaker off.
    const allRejected = ["rejected_ungrounded", "rejected_ungrounded", "rejected_ungrounded"] as const;
    const health = computeEngineHealth(allRejected, 3, 0.3);
    assert.equal(health.rejectionRate, 1);
    assert.equal(health.circuitBreakerTripped, true);
  });

  it("still needs the minimum sample when the window is large", () => {
    const health = computeEngineHealth(["rejected_ungrounded"], 20, 0.3);
    assert.equal(health.circuitBreakerTripped, false);
  });

  it("only considers the most recent window", () => {
    const older = Array.from({ length: 30 }, () => "rejected_ungrounded" as const);
    const health = computeEngineHealth([...older, ...Array.from({ length: 20 }, () => "grounded" as const)], 20, 0.3);
    assert.equal(health.callsInWindow, 20);
    assert.equal(health.rejectedInWindow, 0);
  });
});

describe("isRejection", () => {
  it("treats engine_error as an error, not a grounding rejection", () => {
    assert.equal(isRejection("engine_error"), false);
    assert.equal(isRejection("rejected_ungrounded"), true);
    assert.equal(isRejection("rejected_no_evidence"), true);
    assert.equal(isRejection("grounded"), false);
  });
});
