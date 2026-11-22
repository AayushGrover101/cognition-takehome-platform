document.querySelectorAll("tr[data-dialog]").forEach((row) => {
  const dialog = document.getElementById(row.dataset.dialog);
  const open = () => dialog.showModal();
  row.addEventListener("click", open);
  row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
});
document.querySelectorAll("dialog.modal").forEach((dialog) => {
  dialog.addEventListener("click", (e) => { if (e.target === dialog || e.target.closest("[data-close]")) dialog.close(); });
});
