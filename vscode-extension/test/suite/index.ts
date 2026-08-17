import * as path from "path";
import Mocha from "mocha";
import * as fs from "fs";

export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "tdd", color: true, timeout: 120_000 });
  const testsRoot = __dirname;

  return new Promise((resolve, reject) => {
    const files = fs.readdirSync(testsRoot).filter((f) => f.endsWith(".test.js"));
    for (const file of files) {
      mocha.addFile(path.resolve(testsRoot, file));
    }
    try {
      mocha.run((failures) => {
        if (failures > 0) {
          reject(new Error(`${failures} tests failed.`));
        } else {
          resolve();
        }
      });
    } catch (err) {
      reject(err);
    }
  });
}
