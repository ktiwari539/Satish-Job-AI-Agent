/* Offline read-only handoff and form inspection regression. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ext = path.join(__dirname, "..", "browser-extension", "naukri");
const script = fs.readFileSync(path.join(ext, "ats_form_inspection.js"), "utf8");
const popup = fs.readFileSync(path.join(ext, "popup.js"), "utf8");
const naukriURL = "https://www.naukri.com/job-listings-customer-support-manager-example-123";
const atsURL = "https://jobs.sample-company.example/apply/123?private_token=SECRET";

function field(type, label, isRequired) {
  return {
    tagName: "INPUT", type, required: isRequired,
    // Reject any attempt to inspect values, even in future refactors.
    get value() { throw Error("Private field values must not be accessed"); },
    get checked() { throw Error("Checked state must not be accessed"); },
    get files() { throw Error("Files must not be accessed"); },
    labels: [{textContent: label}],
    getClientRects() { return [1]; },
    getAttribute() { return null; }
  };
}

function inspect(url) {
  const elements = [
    field("email", "Email address", true),
    field("text", "Years of experience", true),
    field("file", "Upload resume", true),
    field("text", "Why do you want this job?", false)
  ];
  const doc = {
    body: {innerText: "Apply for this role"},
    querySelectorAll(selector) {
      if (selector === "input,textarea,select") return elements;
      if (selector === "iframe") return [];
      if (selector.startsWith("button,")) return [{
        textContent: "Submit application",
        getClientRects() { return [1]; },
        getAttribute() { return null; }
      }];
      return [];
    }
  };
  return vm.runInNewContext(script, {
    location: {href: url}, document: doc, URL, Date, Array, String, Set, Math
  }, {filename: "ats_form_inspection.js"});
}

(async () => {
  const observed = inspect(atsURL);
  assert.equal(observed.status, "read_only_inspection");
  assert.equal(observed.site_origin, "https://jobs.sample-company.example");
  assert.equal(observed.submitted, 0);
  assert.equal(observed.confirmed, 0);
  assert.equal(observed.fields.length, 4);
  assert.equal(observed.fields[0].category, "email");
  assert.equal(observed.fields[2].category, "resume");
  assert.equal(observed.action_controls.includes("submit_application"), true);
  assert.equal(JSON.stringify(observed).includes("SECRET"), false);
  assert.equal(inspect("https://accounts.google.com/signin").status, "unsupported_page");
  assert.equal(inspect("https://www.naukri.com/job-listings-example").status, "unsupported_page");

  const elements = new Map();
  for (const id of ["capture", "enrich", "inspect", "handoff", "inspect-ats", "status"]) {
    elements.set(id, {
      disabled: false, textContent: "", events: {},
      addEventListener(name, callback) { this.events[name] = callback; }
    });
  }
  let currentURL = naukriURL;
  let handoff;
  let capturedFile;
  let injections = 0;
  const chrome = {
    tabs: { async query() { return [{id: 7, url: currentURL}]; } },
    scripting: {
      async executeScript({target, files}) {
        assert.equal(target.tabId, 7);
        assert.equal(files[0], "ats_form_inspection.js");
        injections++;
        return [{result: inspect(currentURL)}];
      }
    },
    storage: {
      session: {
        async set(data) { handoff = data.naukri_ats_handoff_v1; },
        async get() { return {naukri_ats_handoff_v1: handoff}; },
        async remove() { handoff = undefined; }
      }
    }
  };
  const browserURL = class extends URL {};
  browserURL.createObjectURL = blob => { capturedFile = blob; return "blob:local"; };
  browserURL.revokeObjectURL = () => {};
  const doc = {
    getElementById(id) { return elements.get(id); },
    createElement() { return { click() {}, remove() {}, set href(x) {}, set download(x) {} }; },
    body: { appendChild() {} }
  };
  vm.runInNewContext(popup, {
    document: doc, chrome, URL: browserURL, Blob, Date, console, setTimeout() {}
  }, {filename: "popup.js"});

  await elements.get("handoff").events.click();
  assert.equal(handoff.source_job_url, naukriURL);
  assert.equal(injections, 0);

  currentURL = atsURL;
  await elements.get("inspect-ats").events.click();
  assert.equal(injections, 1);
  assert.equal(handoff, undefined);
  assert.ok(capturedFile);
  const exported = JSON.parse(await capturedFile.text());
  assert.equal(exported.source_naukri_job_url, naukriURL);
  assert.equal(exported.site_origin, "https://jobs.sample-company.example");
  assert.equal(exported.handoff_method, "user_reported_external_apply");
  assert.equal(exported.handoff_navigation_verified, false);
  assert.equal(exported.submitted, 0);
  assert.equal(exported.confirmed, 0);
  assert.equal(JSON.stringify(exported).includes("SECRET"), false);

  // Fail closed: a later attempt without a fresh handoff cannot inspect.
  await elements.get("inspect-ats").events.click();
  assert.equal(injections, 1);
  assert.match(elements.get("status").textContent, /No fresh Naukri handoff/);

  process.stdout.write("Naukri-to-ATS read-only handoff smoke passed\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
