// The shrunk MiniLM forward pass in plain JavaScript (no libraries). Reads shrunk_int8.bin by manifest_int8.json: matrices are 8-bit rows with one float16
// scale per row, everything else is float16. Same maths as `embed` in export_shrunk_minilm.py: embeddings + LayerNorm, six layers (attention with 12 heads of 32,
// feed-forward 1536 with GELU erf), mean over tokens, L2 normalise. A row's scale is applied after its dot product, which equals multiplying the dequantised row.

function halfToFloat(h) {
  const sign = h & 0x8000 ? -1 : 1, exp = (h >> 10) & 0x1f, frac = h & 0x3ff;
  if (exp === 0) return sign * frac * 2 ** -24;
  if (exp === 31) return frac ? NaN : sign * Infinity;
  return sign * (1 + frac / 1024) * 2 ** (exp - 15);
}

function readHalf(buffer, offset, count) {
  const view = new DataView(buffer, offset, count * 2);
  const out = new Float32Array(count);
  for (let i = 0; i < count; i++) out[i] = halfToFloat(view.getUint16(i * 2, true));
  return out;
}

/** erf by the Chebyshev fit of Numerical Recipes (relative error under 1.2e-7, finer than the float32 the pass runs in). */
function erf(x) {
  const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
  const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return x >= 0 ? 1 - r : r - 1;
}

export function makeEncoder(config, manifest, buffer) {
  const { hidden: H, heads, layers, intermediate: FF, ln_eps: EPS, max_positions: MAXPOS } = config;
  const D = H / heads;

  const matrix = (name) => {
    const m = manifest[name];
    return { q: new Int8Array(buffer, m.q.offset, m.q.length), scale: readHalf(buffer, m.scale.offset, m.scale.shape[0]), rows: m.q.shape[0], cols: m.q.shape[1] };
  };
  const vector = (name) => {
    const m = manifest[name].f16;
    return readHalf(buffer, m.offset, m.length / 2);
  };

  const word = matrix('word');
  const pos = vector('pos'), type0 = vector('type0');
  const embLn = { w: vector('emb_ln.w'), b: vector('emb_ln.b') };
  const lin = (prefix) => ({ ...matrix(prefix + '.w'), b: vector(prefix + '.b') });
  const norm = (prefix) => ({ w: vector(prefix + '.w'), b: vector(prefix + '.b') });
  const stack = Array.from({ length: layers }, (_, i) => {
    const p = `encoder.layer.${i}.`;
    return {
      q: lin(p + 'attention.self.query'), k: lin(p + 'attention.self.key'), v: lin(p + 'attention.self.value'), o: lin(p + 'attention.output.dense'),
      ln1: norm(p + 'attention.output.LayerNorm'), up: lin(p + 'intermediate.dense'), down: lin(p + 'output.dense'), ln2: norm(p + 'output.LayerNorm'),
    };
  });

  /** x (L x cols) times the transpose of an 8-bit matrix (rows x cols), plus its bias: L x rows. */
  function linear(x, L, m) {
    const out = new Float32Array(L * m.rows), { q, scale, rows, cols, b } = m;
    for (let t = 0; t < L; t++) {
      const xo = t * cols;
      for (let r = 0; r < rows; r++) {
        const ro = r * cols;
        let sum = 0;
        for (let c = 0; c < cols; c++) sum += x[xo + c] * q[ro + c];
        out[t * rows + r] = sum * scale[r] + b[r];
      }
    }
    return out;
  }

  function layerNorm(x, L, ln) {
    const out = new Float32Array(L * H);
    for (let t = 0; t < L; t++) {
      const o = t * H;
      let mu = 0;
      for (let c = 0; c < H; c++) mu += x[o + c];
      mu /= H;
      let variance = 0;
      for (let c = 0; c < H; c++) variance += (x[o + c] - mu) ** 2;
      variance /= H;
      const inv = 1 / Math.sqrt(variance + EPS);
      for (let c = 0; c < H; c++) out[o + c] = (x[o + c] - mu) * inv * ln.w[c] + ln.b[c];
    }
    return out;
  }

  function addInto(a, b) {
    for (let i = 0; i < a.length; i++) a[i] += b[i];
    return a;
  }

  function attention(layer, x, L) {
    const q = linear(x, L, layer.q), k = linear(x, L, layer.k), v = linear(x, L, layer.v);
    const ctx = new Float32Array(L * H), scores = new Float32Array(L), norm = 1 / Math.sqrt(D);
    for (let h = 0; h < heads; h++) {
      const ho = h * D;
      for (let i = 0; i < L; i++) {
        let max = -Infinity;
        for (let j = 0; j < L; j++) {
          let s = 0;
          for (let d = 0; d < D; d++) s += q[i * H + ho + d] * k[j * H + ho + d];
          scores[j] = s * norm;
          if (scores[j] > max) max = scores[j];
        }
        let total = 0;
        for (let j = 0; j < L; j++) { scores[j] = Math.exp(scores[j] - max); total += scores[j]; }
        for (let d = 0; d < D; d++) {
          let s = 0;
          for (let j = 0; j < L; j++) s += scores[j] * v[j * H + ho + d];
          ctx[i * H + ho + d] = s / total;
        }
      }
    }
    return linear(ctx, L, layer.o);
  }

  /** ids from the tokenizer ([CLS] ... [SEP]) -> the normalised sentence embedding (Float32Array of 384). */
  return function embed(ids) {
    const L = ids.length;
    if (L > MAXPOS) throw new Error(`${L} pieces is more than the ${MAXPOS} positions of the model`);
    let x = new Float32Array(L * H);
    for (let t = 0; t < L; t++) {
      const row = ids[t] * word.cols, s = word.scale[ids[t]];
      for (let c = 0; c < H; c++) x[t * H + c] = word.q[row + c] * s + pos[t * H + c] + type0[c];
    }
    x = layerNorm(x, L, embLn);
    for (const layer of stack) {
      x = layerNorm(addInto(attention(layer, x, L), x), L, layer.ln1);
      const up = linear(x, L, layer.up);
      for (let i = 0; i < up.length; i++) up[i] = 0.5 * up[i] * (1 + erf(up[i] / Math.SQRT2));
      x = layerNorm(addInto(linear(up, L, layer.down), x), L, layer.ln2);
    }
    const e = new Float32Array(H);
    for (let t = 0; t < L; t++) for (let c = 0; c < H; c++) e[c] += x[t * H + c] / L;
    let n = 0;
    for (let c = 0; c < H; c++) n += e[c] * e[c];
    n = Math.sqrt(n);
    for (let c = 0; c < H; c++) e[c] /= n;
    return e;
  };
}
