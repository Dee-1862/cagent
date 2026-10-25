import React from "react";
import {Composition, registerRoot} from "remotion";
import {Film, TOTAL} from "./Film";
import {FPS} from "./ui";

const Root: React.FC = () => (
  <Composition id="Unstep" component={Film} durationInFrames={TOTAL * FPS} fps={FPS} width={1920} height={1080} />
);

registerRoot(Root);
