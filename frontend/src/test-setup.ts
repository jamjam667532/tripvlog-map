import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

// jsdom에는 scrollIntoView가 없다
Element.prototype.scrollIntoView = () => {};
