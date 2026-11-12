import { describe, expect, it } from "vitest";
import ts from "typescript";
import handlerSource from "./MessageHandler.tsx?raw";

// Execute the production accumulation loop. This exercises its integration
// with removal messages without creating a WebGL canvas in a Node test.
const start = handlerSource.search(/(?:const|let) guiUpdates:/);
const end = handlerSource.indexOf(
  "// Apply all accumulated scene tree updates",
  start,
);
if (start < 0 || end < 0) throw new Error("GUI batching loop not found");
const processMessages = new Function(
  "processBatch",
  "handleMessage",
  "isSceneNodeMessage",
  "parked",
  ts.transpile(handlerSource.slice(start, end) + "\nreturn guiUpdates;", {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.None,
  }),
);

type Update = { uuid: string; updates: Record<string, unknown> };
type Message = Update & { type: "GuiUpdateMessage" };
type Removal = {
  type: "GuiRemoveMessage" | "GuiPanelRemoveMessage" | "GuiCloseModalMessage";
  uuid: string;
};

type Creation = { type: "GuiImageMessage"; uuid: string };

function collect(messages: (Message | Removal | Creation)[]): Update[] {
  return processMessages(
    messages,
    (message: Message | Removal | Creation) =>
      message.type === "GuiUpdateMessage"
        ? { kind: "guiUpdate", uuid: message.uuid, updates: message.updates }
        : undefined,
    () => false,
    { drainFor() {} },
  );
}

const imageData: Message = {
  type: "GuiUpdateMessage",
  uuid: "input-image",
  updates: { _data: "old-png" },
};

describe("GUI updates across component removal", () => {
  it("preserves updates when no component is removed", () => {
    expect(collect([imageData])).toEqual([
      { kind: "guiUpdate", uuid: imageData.uuid, updates: imageData.updates },
    ]);
  });

  it.each([
    "GuiRemoveMessage",
    "GuiPanelRemoveMessage",
    "GuiCloseModalMessage",
  ] as const)("discards updates before %s", (type) => {
    expect(collect([imageData, { type, uuid: imageData.uuid }])).toEqual([]);
  });

  it("keeps other components and their update order", () => {
    const progress: Message = {
      type: "GuiUpdateMessage",
      uuid: "progress",
      updates: { value: 50 },
    };
    const finished: Message = {
      ...progress,
      updates: { value: 100 },
    };
    expect(
      collect([
        progress,
        imageData,
        { type: "GuiRemoveMessage", uuid: imageData.uuid },
        finished,
      ]),
    ).toEqual([
      { kind: "guiUpdate", uuid: "progress", updates: { value: 50 } },
      { kind: "guiUpdate", uuid: "progress", updates: { value: 100 } },
    ]);
  });

  it("keeps only new updates when a removed UUID is reused", () => {
    const replacement: Message = {
      ...imageData,
      updates: { label: "new image" },
    };
    expect(
      collect([
        imageData,
        { type: "GuiRemoveMessage", uuid: imageData.uuid },
        { type: "GuiImageMessage", uuid: imageData.uuid },
        replacement,
      ]),
    ).toEqual([
      { kind: "guiUpdate", uuid: imageData.uuid, updates: replacement.updates },
    ]);
  });

  it("discards all properties queued for an image before its removal", () => {
    expect(
      collect([
        imageData,
        { ...imageData, updates: { label: "old image" } },
        { type: "GuiRemoveMessage", uuid: imageData.uuid },
      ]),
    ).toEqual([]);
  });

  it("retains an invalid update after removal for the existing diagnostics", () => {
    expect(
      collect([
        { type: "GuiRemoveMessage", uuid: imageData.uuid },
        imageData,
      ]),
    ).toEqual([
      { kind: "guiUpdate", uuid: imageData.uuid, updates: imageData.updates },
    ]);
  });
});
