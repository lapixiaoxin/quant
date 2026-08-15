(() => {
  const dropdowns = Array.from(
    document.querySelectorAll(".nav-dropdown"),
  );

  const closeDropdown = (dropdown, restoreFocus = false) => {
    if (!dropdown.open) {
      return;
    }
    dropdown.open = false;
    if (restoreFocus) {
      dropdown.querySelector("summary")?.focus();
    }
  };

  for (const dropdown of dropdowns) {
    let closeTimer;

    dropdown.addEventListener("mouseover", () => {
      if (window.matchMedia("(hover: hover)").matches) {
        window.clearTimeout(closeTimer);
        dropdown.open = true;
      }
    });

    dropdown.addEventListener("mouseleave", () => {
      if (window.matchMedia("(hover: hover)").matches) {
        closeTimer = window.setTimeout(() => {
          closeDropdown(dropdown);
        }, 180);
      }
    });

    dropdown.addEventListener("toggle", () => {
      if (!dropdown.open) {
        return;
      }
      for (const other of dropdowns) {
        if (other !== dropdown) {
          closeDropdown(other);
        }
      }
    });

    dropdown.querySelector("summary")?.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown") {
        return;
      }
      event.preventDefault();
      dropdown.open = true;
      dropdown.querySelector(".nav-menu a")?.focus();
    });
  }

  document.addEventListener("click", (event) => {
    for (const dropdown of dropdowns) {
      if (!dropdown.contains(event.target)) {
        closeDropdown(dropdown);
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    const activeDropdown = dropdowns.find(
      (dropdown) => dropdown.open || dropdown.matches(":focus-within"),
    );
    if (activeDropdown) {
      closeDropdown(activeDropdown, true);
    }
  });
})();
