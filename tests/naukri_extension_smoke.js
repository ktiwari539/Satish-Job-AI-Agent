/* Offline test: explicit read-only Naukri batch, never account or application actions. */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const root = path.join(__dirname, "..", "browser-extension", "naukri");
const workerSource = fs.readFileSync(path.join(root, "background.js"), "utf8");
const captureSource = fs.readFileSync(path.join(root, "detail_capture.js"), "utf8");
const inspectSource = fs.readFileSync(path.join(root, "application_inspection.js"), "utf8");
const jobURL = "https://www.naukri.com/job-listings-customer-success-manager-123";
const description = "Manage customer success outcomes and customer onboarding. ".repeat(8);

function makeHarness({ redirect = false } = {}) {
  let handler;
  let visited = [];
  let removed = [];
  let downloads = [];
  let injected = 0;
  const chrome = {
    runtime: { onMessage: { addListener(fn) { handler = fn; } } },
    tabs: {
      async create({ url, active }) {
        assert.equal(active, false);
        visited.push(url);
        return { id: visited.length, url, status: "complete" };
      },
      async get(id) {
        return { id, status: "complete", url: redirect ? "https://evil.example/job" : visited[id - 1] };
      },
      async remove(id) { removed.push(id); }
    },
    scripting: {
      async executeScript({ target, files }) {
        assert.equal(files.length, 1);
        assert.equal(files[0], "detail_capture.js");
        injected++;
        return [{ result: { url: jobURL, title: "Customer Success Manager",
                            company: "Sample Co", location: "Bengaluru, India",
                            description } }];
      }
    },
    downloads: {
      async download(args) {
        assert.equal(args.saveAs, false);
        assert.match(args.filename, /^naukri-jobs-details-/);
        assert.match(args.url, /^data:application\/json/);
        downloads.push(JSON.parse(decodeURIComponent(args.url.split(",")[1])));
        return 99;
      }
    }
  };
  vm.runInNewContext(workerSource, {
    chrome, URL, JSON, Number, setTimeout: callback => callback()
  }, { filename: "background.js" });
  return {
    send(message) {
      return new Promise(resolve => handler(message, {}, resolve));
    },
    get visited() { return visited; },
    get removed() { return removed; },
    get downloads() { return downloads; },
    get injected() { return injected; },
  };
}

(async () => {
  const harness = makeHarness();
  const result = await harness.send({
    action: "naukri_enrich_jds",
    jobs: [
      { url: jobURL, title: "Customer Success Manager", company: "Sample Co", location: "Bengaluru, India" },
      { url: "https://evil.example/steal-data", title: "Not Naukri" },
      { url: jobURL, title: "Duplicate" },
    ]
  });
  assert.equal(result.status, "exported");
  assert.equal(result.visited, 1);
  assert.equal(result.full_jd, 1);
  assert.deepEqual(harness.visited, [jobURL]);
  assert.equal(harness.removed.length, 1);
  assert.equal(harness.downloads.length, 1);
  assert.equal(harness.downloads[0].page_kind, "detail");
  assert.equal(harness.downloads[0].jobs[0].description, description);

  const redirected = makeHarness({ redirect: true });
  const failed = await redirected.send({
    action: "naukri_enrich_jds",
    jobs: [{ url: jobURL, title: "Customer Success Manager", company: "Sample Co", location: "India" }]
  });
  assert.equal(failed.full_jd, 0);
  assert.equal(redirected.injected, 0);
  assert.equal(redirected.removed.length, 1);
  assert.equal(redirected.downloads[0].jobs[0].description, "");

  const fakeDoc = {
    querySelector(selector) {
      if (selector === "h1") return { innerText: "Customer Success Manager" };
      if (selector === ".jd-header-comp-name") return { innerText: "Sample Co" };
      if (selector === ".location") return { innerText: "Bengaluru, India" };
      if (selector === ".job-desc") return { innerText: description };
      return null;
    },
    querySelectorAll() { return []; }
  };
  const detail = vm.runInNewContext(captureSource, {
    document: fakeDoc, location: { href: jobURL },
    URL, JSON, String, DOMParser: class {}
  }, { filename: "detail_capture.js" });
  assert.equal(detail.description, description.trim());
  assert.equal(detail.url, jobURL);
  const noCapture = vm.runInNewContext(captureSource, {
    document: fakeDoc, location: { href: "https://example.com/job" },
    URL, JSON, String, DOMParser: class {}
  }, { filename: "detail_capture.js" });
  assert.equal(noCapture.description, "");

  // Supervised review inspection must classify visible controls without reading
  // input values or clicking Apply/Submit.
  class InspectNode {
    constructor(text) { this.innerText = text; this.textContent = text; }
    getClientRects() { return [1]; }
    getAttribute() { return null; }
  }
  const buttons = [new InspectNode("Apply Now"), new InspectNode("Login")];
  const input = { tagName: "INPUT", type: "email", required: true,
                  value: "private@example.invalid",
                  getAttribute() { return null; } };
  const inspectDoc = {
    body: {innerText: "Job description and Apply Now"},
    querySelectorAll(selector) {
      if (selector.startsWith("button,")) return buttons;
      if (selector.startsWith("input,")) return [input];
      if (selector === "iframe") return [];
      return [];
    }
  };
  const inspection = vm.runInNewContext(inspectSource, {
    document: inspectDoc, location: {href: jobURL},
    URL, JSON, Date, String, Element: InspectNode, Set, Array, Math
  });
  assert.equal(inspection.mode, "READ_ONLY_INSPECTION");
  assert.equal(inspection.job_url, jobURL);
  assert.equal(inspection.application_controls.includes("apply"), true);
  assert.equal(inspection.required_field_types.includes("email"), true);
  assert.equal(JSON.stringify(inspection).includes("private@example.invalid"), false);

  const unsupported = vm.runInNewContext(inspectSource, {
    document: inspectDoc, location: {href: "https://example.com/job"},
    URL, JSON, Date, String, Element: InspectNode, Set, Array, Math
  });
  assert.equal(unsupported.job_url, "");
  assert.equal(unsupported.application_controls.length, 0);

  process.stdout.write("Naukri extension read-only smoke tests passed\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
