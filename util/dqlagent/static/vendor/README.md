# Vendored browser libraries

The chat page draws graphs with React Flow. These files are the unmodified
builds from npm, committed so the page needs no npm, bundler or CDN: the
browser loads them from the local chat server, which also works offline and
inside a VPC without internet access. All three packages are MIT licensed
(`LICENSES.txt`).

`jsx-runtime-shim.js` is ours: React 18 ships no UMD build of
`react/jsx-runtime`, which the React Flow UMD build expects as the global
`jsxRuntime`, so the shim provides it with `React.createElement`.

| File | Package | Path in the package | SHA-256 |
|------|---------|---------------------|---------|
| `react.production.min.js` | `react` 18.3.1 | `umd/react.production.min.js` | `d949f1c3687aedadcedac85261865f29b17cd273997e7f6b2bfc53b2f9d4c4dd` |
| `react-dom.production.min.js` | `react-dom` 18.3.1 | `umd/react-dom.production.min.js` | `35f4f974f4b2bcd44da73963347f8952e341f83909e4498227d4e26b98f66f0d` |
| `xyflow-react.umd.js` | `@xyflow/react` 12.12.0 | `dist/umd/index.js` | `c418896c3d0cc63498e724df7ed9698532c58523c04d30ebcd3ff7fa0bf3ecff` |
| `xyflow-react.css` | `@xyflow/react` 12.12.0 | `dist/style.css` | `7ed5ae87a6c9bd664fce1802ce33fbe84faaefe33e21c82be35529df06e0c686` |

To update: download the package tarballs from the npm registry, copy the same
paths, update this table, and check the chat page still draws a graph.
