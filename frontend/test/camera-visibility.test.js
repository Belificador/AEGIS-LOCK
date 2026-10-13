import assert from "node:assert/strict";
import test from "node:test";

import { HIDDEN_CAMERA_IDS, isCameraHidden } from "../src/components/viewport/camera-visibility.js";

test("hides only the L2 and conference cameras from the dashboard", () => {
  assert.deepEqual([...HIDDEN_CAMERA_IDS].sort(), ["CAM_02_CONFERENCIAS", "CAM_05_OFICINA_L2"]);
  assert.equal(isCameraHidden("CAM_05_OFICINA_L2"), true);
  assert.equal(isCameraHidden("CAM_02_CONFERENCIAS"), true);
  assert.equal(isCameraHidden("CAM_01_GERENCIA"), false);
});
