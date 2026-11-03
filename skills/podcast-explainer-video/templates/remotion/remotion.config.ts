// Render defaults for the podcast-explainer-video skill. CLI flags override these.
// See references/remotion.md for the render command and the concurrency benchmark.
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setCodec("h264");
Config.setCrf(18);
Config.setOverwriteOutput(true);
Config.setEntryPoint("src/index.ts");
