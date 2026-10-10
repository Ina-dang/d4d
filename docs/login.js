"use strict";

// Presentation-only entry to the local scenario UI. Server authentication is not implemented.
const form = document.getElementById("login-form");
const number = document.getElementById("login-number");
const password = document.getElementById("login-password");
const remember = document.getElementById("remember-number");
const feedback = document.getElementById("login-feedback");
const storageKey = "gyeopnun.login.number";

try {
  const savedNumber = localStorage.getItem(storageKey);
  if (savedNumber) {
    number.value = savedNumber;
    remember.checked = true;
  }
} catch {
  // Login still works when browser storage is unavailable.
}

remember.addEventListener("change", () => {
  if (!remember.checked) {
    try { localStorage.removeItem(storageKey); } catch { /* Storage may be disabled. */ }
  }
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!number.value.trim() || !password.value.trim()) {
    feedback.textContent = "번호와 비밀번호를 입력하세요.";
    feedback.hidden = false;
    (!number.value.trim() ? number : password).focus();
    return;
  }
  try {
    if (remember.checked) localStorage.setItem(storageKey, number.value.trim());
    else localStorage.removeItem(storageKey);
  } catch {
    // Never store the password or block entry because storage failed.
  }
  password.value = "";
  window.location.assign("storyboard.html?screen=scope");
});
