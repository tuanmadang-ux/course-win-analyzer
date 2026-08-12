import { Config } from "@remotion/cli/config";

// Thẻ được chồng lên video nên bắt buộc phải có kênh alpha.
Config.setVideoImageFormat("png");
Config.setPixelFormat("yuva444p10le");
Config.setCodec("prores");
Config.setProResProfile("4444");
