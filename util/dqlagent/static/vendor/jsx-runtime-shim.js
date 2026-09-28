// React 18 has no UMD build of react/jsx-runtime; the React Flow UMD build
// expects it as the global `jsxRuntime`. jsx(type, props, key) maps onto
// createElement(type, props): children travel inside props, key separately.
(function () {
  "use strict";
  var React = window.React;
  function jsx(type, props, key) {
    if (key !== undefined) {
      props = Object.assign({}, props, { key: key });
    }
    return React.createElement(type, props);
  }
  window.jsxRuntime = { jsx: jsx, jsxs: jsx, Fragment: React.Fragment };
})();
