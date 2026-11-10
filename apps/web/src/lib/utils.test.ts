import { describe, expect, it } from "vitest";

import { safeHttpUrl } from "./utils";

describe("safeHttpUrl", () => {
  it("keeps absolute http(s) links", () => {
    expect(safeHttpUrl("https://grants.example.org/call?id=1")).toBe("https://grants.example.org/call?id=1");
    expect(safeHttpUrl(" http://example.com/x ")).toBe("http://example.com/x");
  });

  it("drops script, data and other schemes, relative links and non-strings", () => {
    for (const bad of ["javascript:alert(1)", " JaVaScRiPt:alert(1)", "data:text/html,<script>x</script>",
                       "vbscript:x", "file:///etc/passwd", "/relative", "//evil.example", "", "   ", null, undefined, 42]) {
      expect(safeHttpUrl(bad)).toBeUndefined();
    }
  });
});
