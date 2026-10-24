// Query embeddings in JavaScript: all-MiniLM-L6-v2, 16-bit (fp16, 45 MB), through Transformers.js (the same model the Python side used, so the catalogue embeddings in
// wording_embeddings.f32 stay valid). Owner's choice, 2026-10-24: parity.mjs stage B gave 0 visible differences for fp16 and 70 of 1,522 for the 8-bit (q8, 23 MB) model.
import { env, pipeline } from "@huggingface/transformers";

export const MODEL = "Xenova/all-MiniLM-L6-v2";

export async function makeEmbedder({ cacheDir = new URL("./model_cache", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1") } = {}) {
  env.cacheDir = cacheDir;
  const extractor = await pipeline("feature-extraction", MODEL, { dtype: (globalThis.process && process.env.PACKSENSE_DTYPE) || "fp16" });
  return async (text) => {
    const out = await extractor(text, { pooling: "mean", normalize: true });
    return Float32Array.from(out.data);
  };
}
