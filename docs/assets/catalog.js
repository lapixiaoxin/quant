(() => {
  const forms = document.querySelectorAll("[data-catalog-filters]");
  for (const form of forms) {
    const catalogId = form.dataset.catalogFilters;
    const catalog = document.querySelector(`[data-catalog="${catalogId}"]`);
    if (!catalog) {
      continue;
    }
    const rows = Array.from(catalog.querySelectorAll("[data-catalog-row]"));
    const count = document.querySelector(`[data-catalog-count="${catalogId}"]`);
    const controls = Array.from(
      form.querySelectorAll("input[data-field], select[data-field]"),
    );
    const apply = () => {
      let visible = 0;
      const filtering = controls.some((control) => control.value.trim());
      for (const row of rows) {
        const matched = controls.every((control) => {
          const expected = control.value.trim().toLowerCase();
          if (!expected) {
            return true;
          }
          const field = control.dataset.field;
          const actual = (
            field === "text"
              ? row.textContent
              : row.dataset[field] || ""
          ).toLowerCase();
          return actual.includes(expected);
        });
        row.hidden = !matched;
        if (matched) {
          visible += 1;
        }
      }
      for (const group of catalog.querySelectorAll(".resource-group")) {
        const hasMatch = Boolean(group.querySelector(
          "[data-catalog-row]:not([hidden])",
        ));
        group.hidden = !hasMatch;
        group.open = filtering && hasMatch;
      }
      if (count) {
        count.textContent = `${visible} / ${rows.length}`;
      }
    };
    for (const control of controls) {
      control.addEventListener("input", apply);
      control.addEventListener("change", apply);
    }
    form.addEventListener("reset", () => window.setTimeout(apply, 0));
    apply();
  }
})();
