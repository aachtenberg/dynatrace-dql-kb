// A small Markdown renderer for model answers. It builds DOM nodes and sets
// text with textContent only, so nothing in an answer is ever parsed as HTML.
// Covers what the agent writes: paragraphs, headings, lists, tables, block
// quotes, fenced code (with a copy button), inline code, bold, italic, links.
(function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  var INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))|(\*[^*\s][^*]*\*)|(_[^_\s][^_]*_)/g;

  function inline(parent, text) {
    var last = 0, m;
    INLINE.lastIndex = 0;
    while ((m = INLINE.exec(text)) !== null) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      var t = m[0];
      if (m[1]) {
        parent.appendChild(el("code", null, t.slice(1, -1)));
      } else if (m[2]) {
        var b = el("strong");
        inline(b, t.slice(2, -2));
        parent.appendChild(b);
      } else if (m[3]) {
        var a = el("a", null, m[4]);
        a.href = m[5];
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        parent.appendChild(a);
      } else {
        var i = el("em");
        inline(i, t.slice(1, -1));
        parent.appendChild(i);
      }
      last = m.index + t.length;
      INLINE.lastIndex = last;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  function copyButton(getText) {
    var btn = el("button", "ghost copy", "Copy");
    btn.type = "button";
    btn.addEventListener("click", function () {
      var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(getText()).then(done, function () { btn.textContent = "Copy failed"; });
      }
    });
    return btn;
  }

  function codeBlock(code, lang) {
    var wrap = el("div", "codeblock");
    var pre = el("pre");
    var c = el("code", lang ? "lang-" + lang : null, code);
    pre.appendChild(c);
    wrap.appendChild(pre);
    wrap.appendChild(copyButton(function () { return code; }));
    return wrap;
  }

  function splitRow(line) {
    var s = line.trim();
    if (s.charAt(0) === "|") s = s.slice(1);
    if (s.charAt(s.length - 1) === "|") s = s.slice(0, -1);
    return s.split("|").map(function (c) { return c.trim(); });
  }

  var LIST = /^\s*([-*+]|\d+[.)])\s+(.*)$/;
  var BLOCK_START = /^\s*(```|#{1,6}\s|>|\|)/;

  function render(src) {
    var frag = document.createDocumentFragment();
    var lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      var fence = line.match(/^\s*```\s*([\w-]*)\s*$/);
      if (fence) {
        var code = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        frag.appendChild(codeBlock(code.join("\n"), fence[1]));
        continue;
      }
      if (/^\s*$/.test(line)) { i++; continue; }
      var h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        var hn = el("h" + Math.min(4, h[1].length + 1));
        inline(hn, h[2]);
        frag.appendChild(hn);
        i++;
        continue;
      }
      if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        var table = el("table"), thead = el("thead"), tbody = el("tbody"), tr = el("tr");
        splitRow(line).forEach(function (cell) { var th = el("th"); inline(th, cell); tr.appendChild(th); });
        thead.appendChild(tr);
        i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          var row = el("tr");
          splitRow(lines[i]).forEach(function (cell) { var td = el("td"); inline(td, cell); row.appendChild(td); });
          tbody.appendChild(row);
          i++;
        }
        table.appendChild(thead);
        table.appendChild(tbody);
        frag.appendChild(table);
        continue;
      }
      var li = line.match(LIST);
      if (li) {
        var ordered = /\d/.test(li[1]);
        var list = el(ordered ? "ol" : "ul");
        while (i < lines.length && (li = lines[i].match(LIST)) && /\d/.test(li[1]) === ordered) {
          var item = el("li");
          inline(item, li[2]);
          i++;
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !LIST.test(lines[i])) {
            item.appendChild(document.createTextNode(" "));
            inline(item, lines[i].trim());
            i++;
          }
          list.appendChild(item);
        }
        frag.appendChild(list);
        continue;
      }
      if (/^\s*>/.test(line)) {
        var quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
        var bq = el("blockquote");
        bq.appendChild(render(quote.join("\n")));
        frag.appendChild(bq);
        continue;
      }
      var para = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !BLOCK_START.test(lines[i]) && !LIST.test(lines[i])) {
        para.push(lines[i].trim());
        i++;
      }
      if (!para.length) { para.push(line.trim()); i++; }
      var p = el("p");
      inline(p, para.join(" "));
      frag.appendChild(p);
    }
    return frag;
  }

  window.DqlMarkdown = { render: render, inline: inline, codeBlock: codeBlock, copyButton: copyButton };
})();
