const PITCH_DOWNLOAD_URL = "https://www2.pitch.se/free/download.asp";
const DEFAULTS = {
  destination_email: "you@example.com",
  first_name: "John",
  last_name: "Doe",
  title: "Engineer",
  organization: "Self",
  organization_type: "Other",
  country: "United States",
  accepted_products: [
    "Pitch pRTI Free",
    "Pitch Visual OMT Free",
    "HLA Starter kit",
    "HLA Tutorial",
    "Pitch Unreal Engine Connector Free",
  ],
  subscribe_newsletter: false,
};

function normalize(value) {
  return String(value || "").toLowerCase().replace(/[\s:_-]+/g, " ").replace(/\s+/g, " ").trim();
}

function textMatches(needle, haystack) {
  return normalize(haystack).includes(normalize(needle));
}

function getCandidateContainers() {
  return [...document.querySelectorAll("tr,li,p,div,fieldset,td,th,label")];
}

function findContainer(needle) {
  const match = getCandidateContainers().find((el) => textMatches(needle, el.textContent));
  return match ? match.closest("tr,li,p,div,fieldset,td,th") || match.parentElement : null;
}

function fire(field) {
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
}

function setValue(needle, value) {
  if (!value) return false;
  const container = findContainer(needle);
  if (!container) return false;
  const field = container.querySelector("input:not([type=checkbox]):not([type=radio]),textarea,select");
  if (!field) return false;
  field.value = value;
  fire(field);
  return true;
}

function clickCheckbox(needle) {
  const container = findContainer(needle);
  if (!container) return false;
  const field = container.querySelector("input[type=checkbox]");
  if (!field) return false;
  if (!field.checked) field.click();
  return true;
}

function clickRadio(groupNeedle, optionNeedle) {
  const container = findContainer(groupNeedle);
  if (!container) return false;
  for (const radio of container.querySelectorAll("input[type=radio]")) {
    const labelText = radio.closest("label")?.textContent || radio.parentElement?.textContent || radio.nextElementSibling?.textContent || "";
    if (textMatches(optionNeedle, labelText)) {
      if (!radio.checked) radio.click();
      return true;
    }
  }
  return false;
}

function findSubmitButton() {
  const candidates = [...document.querySelectorAll("button, input[type=submit], input[type=button]")];
  return candidates.find((element) => {
    const label = element.value || element.textContent || "";
    return textMatches("submit", label);
  }) || null;
}

function submitForm() {
  const button = findSubmitButton();
  if (!button) {
    console.warn("No submit button was found on the page.");
    return false;
  }
  button.click();
  return true;
}

function fillForm(contact) {
  setValue("e-mail address", contact.destination_email);
  setValue("first name", contact.first_name);
  setValue("last name", contact.last_name);
  setValue("title/position", contact.title);
  setValue("name of organization", contact.organization);
  setValue("country", contact.country);
  clickRadio("type of organization", contact.organization_type);

  for (const product of contact.accepted_products || []) {
    clickCheckbox(product);
    if (textMatches("Pitch pRTI Free", product)) clickCheckbox("I accept the Pitch pRTI license agreement");
    if (textMatches("Pitch Visual OMT Free", product)) clickCheckbox("I accept the Pitch Visual OMT license agreement");
    if (textMatches("Pitch Unreal Engine Connector Free", product)) clickCheckbox("I accept the Pitch Unreal Engine Connector license agreement");
  }

  if (contact.subscribe_newsletter) {
    clickCheckbox("Subscribe to Pitch Newsletter");
  }

  const emailField = findContainer("e-mail address")?.querySelector("input");
  if (emailField) emailField.focus();
}

function main() {
  if (typeof document === "undefined") {
    throw new Error("This script runs in a browser context only.");
  }

  if (!location.href.includes("pitch.se/free/download.asp")) {
    console.warn("Open the Pitch free download page first:", PITCH_DOWNLOAD_URL);
  }

  const email = window.prompt("Pitch destination email", DEFAULTS.destination_email || "");
  if (!email) {
    console.warn("No email was entered.");
    return;
  }

  const contact = Object.assign({}, DEFAULTS, { destination_email: email });
  fillForm(contact);

  if (window.confirm("Submit the Pitch form now?")) {
    submitForm();
  }
}

main();
