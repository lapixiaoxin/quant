(() => {
  const content = document.querySelector("#markdown-content");
  const pathLabel = document.querySelector("#reader-path");
  const rawLink = document.querySelector("#reader-raw");

  const fail = (message) => {
    content.innerHTML = "";
    const state = document.createElement("p");
    state.className = "reader-state reader-error";
    state.textContent = message;
    content.append(state);
  };

  const sourceValue = (
    document.body.dataset.markdownSource
    || new URLSearchParams(window.location.search).get("src")
  );
  if (!sourceValue) {
    fail("缺少 Markdown 文件路径。");
    return;
  }

  const sourceUrl = new URL(sourceValue, window.location.href);
  if (
    sourceUrl.origin !== window.location.origin
    || !sourceUrl.pathname.toLowerCase().endsWith(".md")
  ) {
    fail("只允许读取当前站点内的 Markdown 文件。");
    return;
  }

  const rewriteAssets = () => {
    for (const link of content.querySelectorAll("a[href]")) {
      const value = link.getAttribute("href");
      if (!value || value.startsWith("#")) {
        continue;
      }
      const target = new URL(value, sourceUrl);
      if (
        target.origin === window.location.origin
        && target.pathname.toLowerCase().endsWith(".md")
      ) {
        const source = encodeURIComponent(target.pathname + target.search);
        link.href = `${window.location.pathname}?src=${source}${target.hash}`;
        continue;
      }
      link.href = target.href;
      if (target.origin !== window.location.origin) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    }
    for (const image of content.querySelectorAll("img[src]")) {
      const target = new URL(image.getAttribute("src"), sourceUrl);
      if (!["http:", "https:"].includes(target.protocol)) {
        image.remove();
        continue;
      }
      image.src = target.href;
      image.loading = "lazy";
    }
    const usedIds = new Set();
    for (const [index, heading] of Array.from(
      content.querySelectorAll("h1, h2, h3, h4, h5, h6"),
    ).entries()) {
      const base = heading.textContent
        .trim()
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fff]+/g, "-")
        .replace(/^-|-$/g, "") || `section-${index + 1}`;
      let id = base;
      let suffix = 2;
      while (usedIds.has(id)) {
        id = `${base}-${suffix}`;
        suffix += 1;
      }
      usedIds.add(id);
      heading.id = id;
    }
  };

  fetch(sourceUrl, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.text();
    })
    .then((markdown) => {
      const rendered = window.marked.parse(markdown, {
        gfm: true,
        breaks: false,
      });
      content.innerHTML = window.DOMPurify.sanitize(rendered, {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ["form", "iframe", "object", "script", "style"],
      });
      rewriteAssets();
      const heading = content.querySelector("h1");
      const filename = decodeURIComponent(
        sourceUrl.pathname.split("/").pop() || "Markdown",
      );
      const title = heading?.textContent.trim() || filename;
      document.title = `${title} · Quant Monitor`;
      if (pathLabel) {
        pathLabel.textContent = filename;
      }
      if (rawLink) {
        rawLink.href = sourceUrl.href;
        rawLink.hidden = false;
      }
      if (window.location.hash) {
        document.getElementById(
          decodeURIComponent(window.location.hash.slice(1)),
        )?.scrollIntoView();
      }
    })
    .catch((error) => {
      fail(`文件读取失败：${error.message}`);
    });
})();
