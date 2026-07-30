"use strict";

const baseInferenceFormPayload = formPayload;
formPayload = function optimizedInferenceFormPayload(form) {
  const payload = baseInferenceFormPayload(form);
  const data = new FormData(form);
  const sample = Number(String(data.get("request_event_sample") || "20"));
  return {
    ...payload,
    inference_mode: String(data.get("inference_mode") || "adaptive"),
    parallel_characters: data.has("parallel_characters"),
    adaptive_confirmation: data.has("adaptive_confirmation"),
    adaptive_concurrency: data.has("adaptive_concurrency"),
    request_event_sample: Number.isFinite(sample) ? sample : 20,
  };
};
