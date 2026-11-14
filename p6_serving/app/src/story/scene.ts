import { BEATS, captionOpacity, clamp01, ease, lerp, seg } from './timeline';

/**
 * Where everything in the story is for a given scroll progress `p` (0 to 1), as CSS custom properties. The stage sets them on itself once a frame
 * and the style sheet turns them into positions, so a scroll costs no React render. The picture is a camera flying forward through layers that stand
 * one behind the other: each layer arrives from far away, rests in front of the camera, and flies past it.
 */
export type SceneVars = Record<string, string>;

/** A layer's journey: it arrives over [a, b], rests until c, and leaves over [c, d]. */
interface Pass {
  a: number;
  b: number;
  c: number;
  d: number;
}

const FAR = -1800;
const NEAR = 800;

export const PASSES = {
  raw: { a: 0.12, b: 0.26, c: 0.4, d: 0.5 },
  clean: { a: 0.36, b: 0.48, c: 0.6, d: 0.7 },
  tables: { a: 0.56, b: 0.68, c: 0.78, d: 0.86 },
  result: { a: 0.74, b: 0.84, c: 0.93, d: 1 },
} satisfies Record<string, Pass>;

/** The depth, the sideways turn and the opacity of a layer that arrives, rests and leaves. */
export function pass(p: number, { a, b, c, d }: Pass): { z: number; ry: number; o: number } {
  const arriving = ease(seg(p, a, b));
  const leaving = ease(seg(p, c, d));
  return {
    z: p < c ? lerp(FAR, 0, arriving) : lerp(0, NEAR, leaving),
    ry: p < c ? lerp(14, 0, arriving) : lerp(0, -8, leaving),
    o: Math.min(seg(p, a, a + (b - a) * 0.5), 1 - seg(p, c + (d - c) * 0.2, d)),
  };
}

const px = (n: number) => `${n.toFixed(1)}px`;
const deg = (n: number) => `${n.toFixed(2)}deg`;
const num = (n: number) => n.toFixed(3);

function layer(name: string, p: number, path: Pass): SceneVars {
  const { z, ry, o } = pass(p, path);
  return { [`--${name}-z`]: px(z), [`--${name}-ry`]: deg(ry), [`--${name}-o`]: num(o) };
}

export function sceneVars(rawProgress: number): SceneVars {
  const p = clamp01(rawProgress);

  // The daily file: small and far away at the start, it flies toward the camera and turns into the raw copy.
  const flight = ease(seg(p, 0, 0.2));
  const file: SceneVars = {
    '--file-z': px(lerp(-2200, 0, flight)),
    '--file-x': px(lerp(300, 0, flight)),
    '--file-y': px(lerp(-140, 0, flight)),
    '--file-o': num(1 - seg(p, 0.13, 0.22)),
  };

  // Tables fan out of the one record while they arrive.
  const spread = ease(seg(p, 0.6, 0.74));
  // The page at the end: it grows from far away and stays.
  const page = ease(seg(p, 0.86, 0.99));

  const vars: SceneVars = {
    ...file,
    ...layer('raw', p, PASSES.raw),
    ...layer('clean', p, PASSES.clean),
    ...layer('tables', p, PASSES.tables),
    ...layer('result', p, PASSES.result),
    '--page-z': px(lerp(FAR, 0, page)),
    '--page-o': num(seg(p, 0.86, 0.93)),
    // Inside the layers: the username turns into a hidden code, the unused fields drop away, 245 becomes 81, the tables spread, the bars grow.
    '--swap': num(ease(seg(p, 0.44, 0.54))),
    '--drop': num(ease(seg(p, 0.47, 0.58))),
    '--spread': num(spread),
    '--bars': num(ease(seg(p, 0.76, 0.88))),
    '--progress': num(p),
  };
  BEATS.forEach((beat, i) => {
    vars[`--caption-${i}`] = num(captionOpacity(p, beat));
  });
  return vars;
}
