#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const modelDir = process.env.AGENT_INSTRUCTIONS_DIR ?? ".ai-badger/agent-instructions";
const modelPath = path.join(root, modelDir, "model.json");
const errors = [];

function readJson(filePath) {
  try {
    return JSON.parse(readFileSync(filePath, "utf8"));
  } catch (error) {
    errors.push(`Failed to parse ${path.relative(root, filePath)}: ${error.message}`);
    return undefined;
  }
}

function readText(relativePath) {
  return readFileSync(path.join(root, relativePath), "utf8");
}

function matchesAny(text, patterns) {
  return patterns.some((pattern) => new RegExp(pattern, "is").test(text));
}

function checkRule(rule, kind) {
  for (const relativePath of rule.mustAppearIn) {
    const absolutePath = path.join(root, relativePath);
    if (!existsSync(absolutePath)) {
      errors.push(`${kind} ${rule.id} expects missing file ${relativePath}`);
      continue;
    }

    const text = readText(relativePath);
    if (!matchesAny(text, rule.patterns)) {
      errors.push(`${relativePath} does not mention ${kind} ${rule.id}: ${rule.summary ?? rule.id}`);
    }
  }
}

if (!existsSync(modelPath)) {
  errors.push(`Missing ${path.join(modelDir, "model.json")}`);
} else {
  const model = readJson(modelPath);
  if (model) {
    for (const invariant of model.sharedPolicy?.nonNegotiableInvariants ?? []) {
      checkRule(invariant, "invariant");
    }

    for (const category of model.sharedPolicy?.reviewCategories ?? []) {
      checkRule(category, "review category");
    }
  }
}

if (errors.length > 0) {
  console.error("Agent instruction drift detected:");
  for (const error of errors) {
    console.error(`- ${error}`);
  }
  process.exit(1);
}

console.log("Agent instruction drift check passed.");
