import fs from "node:fs";
const input = new URL(
  "../../docs/verification/m1-openapi.json",
  import.meta.url,
);
const output = new URL("../src/m1/types.ts", import.meta.url);
const spec = JSON.parse(fs.readFileSync(input, "utf8"));
function type(s) {
  if (s.$ref) return s.$ref.split("/").at(-1);
  if (s.const !== undefined) return JSON.stringify(s.const);
  if (s.enum) return s.enum.map((v) => JSON.stringify(v)).join(" | ");
  if (s.anyOf) return s.anyOf.map(type).join(" | ");
  if (s.type === "array") return `Array<${type(s.items || {})}>`;
  if (s.type === "object" || s.properties) {
    if (!s.properties)
      return `Record<string, ${typeof s.additionalProperties === "object" ? type(s.additionalProperties) : "unknown"}>`;
    return `{ ${Object.entries(s.properties)
      .map(
        ([k, v]) =>
          `${JSON.stringify(k)}${s.required?.includes(k) ? "" : "?"}: ${type(v)}`,
      )
      .join("; ")} }`;
  }
  return (
    {
      string: "string",
      integer: "number",
      number: "number",
      boolean: "boolean",
      null: "null",
    }[s.type] || "unknown"
  );
}
const result =
  "// Generated from docs/verification/m1-openapi.json. Do not edit.\n" +
  Object.entries(spec.components.schemas)
    .map(([name, schema]) => `export type ${name} = ${type(schema)};`)
    .join("\n") +
  "\n";
if (process.argv.includes("--check")) {
  if (fs.readFileSync(output, "utf8") !== result)
    throw new Error("M1 API types drifted; run npm run types:api");
} else {
  fs.mkdirSync(new URL("../src/m1/", import.meta.url), { recursive: true });
  fs.writeFileSync(output, result);
}
