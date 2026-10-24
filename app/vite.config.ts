import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative asset paths: the same build runs at the root on Vercel and under /pilot/ on the hub.
export default defineConfig({ base: "./", plugins: [react()] });
