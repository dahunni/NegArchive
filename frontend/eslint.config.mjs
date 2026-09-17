// ESLint flat config (roadmap M3: a lint step in CI, with its config checked in).
//
// `next lint` is gone in Next 16, so `npm run lint` calls ESLint directly with
// `eslint-config-next`, which is where the Next-specific rules live: the ones
// that catch a synchronous `<img>` where `next/image` belongs, a client hook in
// a server component, or a missing dependency in an effect.
//
// The overrides below exist because a *self-hosted, offline-first* archive does
// not want some of the defaults — `next/image`'s optimiser is switched off in
// `next.config.mjs` on purpose, so a plain `<img>` is the right tag here.

import next from "eslint-config-next"
import nextTypescript from "eslint-config-next/typescript"

export default [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/sw.js"],
  },
  ...next,
  ...nextTypescript,
  {
    rules: {
      // `images.unoptimized` is true: the archive has no internet and no CDN, so
      // `next/image`'s loader buys nothing and `<img>` is honest.
      "@next/next/no-img-element": "off",

      // These two are new in Next 16's config (the React Compiler rules). They
      // fire on "fetch on mount, then setState", which is how every M1 component
      // and three of M3's load their data. The advice is sound and worth taking,
      // but rewriting a dozen working components is its own change, not
      // something to smuggle into the milestone that turned linting on: warnings
      // now, errors once somebody has actually done that rewrite.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
    },
  },
  {
    // The shadcn components are vendored, near-verbatim upstream code. Linting
    // them tells us about upstream's style, not about ours.
    files: ["components/ui/**"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-empty-object-type": "off",
    },
  },
]
