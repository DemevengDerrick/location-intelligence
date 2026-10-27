// FR-43: ask for a clearer wording of one finding; the analyst accepts or dismisses it.
document.addEventListener("DOMContentLoaded", () => {
  const configElement = document.getElementById("suggest-config");
  if (!configElement) return;
  const config = JSON.parse(configElement.textContent);
  const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;

  document.querySelectorAll("button.suggest").forEach((button) => {
    button.addEventListener("click", async () => {
      const textarea = document.querySelector(`textarea[name="${button.dataset.target}"]`);
      let box = button.nextElementSibling;
      if (!box || !box.classList.contains("suggestion")) {
        box = document.createElement("div");
        box.className = "suggestion";
        box.setAttribute("aria-live", "polite");
        button.after(box);
      }
      box.replaceChildren(document.createTextNode(config.working));
      button.disabled = true;
      try {
        const body = new URLSearchParams({ text: textarea.value, language: button.dataset.language });
        const response = await fetch(config.url, {
          method: "POST",
          headers: { "X-CSRFToken": csrf },
          body,
          credentials: "same-origin",
        });
        const data = await response.json();
        if (!response.ok) {
          box.replaceChildren(document.createTextNode(data.error || response.statusText));
          return;
        }
        const text = document.createElement("p");
        text.textContent = data.suggestion;
        const accept = document.createElement("button");
        accept.type = "button";
        accept.textContent = config.accept;
        accept.addEventListener("click", () => { textarea.value = data.suggestion; box.remove(); });
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.textContent = config.dismiss;
        dismiss.addEventListener("click", () => box.remove());
        box.replaceChildren(text, accept, document.createTextNode(" "), dismiss);
      } finally {
        button.disabled = false;
      }
    });
  });
});
