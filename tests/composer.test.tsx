import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskComposer } from "../src/components/TaskComposer";
import { Api, ApiError } from "../src/lib/api";

const apiWith = (createTask: Api["createTask"]) => ({ createTask }) as unknown as Api;
const noop = () => undefined;

describe("TaskComposer", () => {
  it("will not start until the task has a few words and setup is done", async () => {
    render(<TaskComposer api={apiWith(vi.fn())} ready={true} onCreated={noop} onOpenSetup={noop} />);
    const start = screen.getByRole("button", { name: "Start task" });
    expect(start).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Task"), "ab");
    expect(start).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Task"), "c");
    expect(start).toBeEnabled();
  });

  it("only complains about setup when it is known to be unfinished", () => {
    const { rerender } = render(<TaskComposer api={apiWith(vi.fn())} ready={null} onCreated={noop} onOpenSetup={noop} />);
    expect(screen.queryByText(/Setup is not finished/)).not.toBeInTheDocument();
    rerender(<TaskComposer api={apiWith(vi.fn())} ready={false} onCreated={noop} onOpenSetup={noop} />);
    expect(screen.getByText(/Setup is not finished/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start task" })).toBeDisabled();
  });

  it("starts the task, passes the starting site, and clears the box", async () => {
    const created = { id: 5 };
    const createTask = vi.fn().mockResolvedValue(created);
    const onCreated = vi.fn();
    render(<TaskComposer api={apiWith(createTask)} ready={true} onCreated={onCreated} onOpenSetup={noop} />);
    await userEvent.type(screen.getByLabelText("Task"), "Find the price of Dune");
    await userEvent.type(screen.getByPlaceholderText("Start on a website (optional)"), "example.com");
    await userEvent.click(screen.getByRole("button", { name: "Start task" }));
    expect(createTask).toHaveBeenCalledWith("Find the price of Dune", "example.com");
    expect(onCreated).toHaveBeenCalledWith(created);
    expect((screen.getByLabelText("Task") as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps what was typed and explains when the service refuses", async () => {
    const createTask = vi.fn().mockRejectedValue(new ApiError(422, "The starting address must be a normal website address (http or https)."));
    render(<TaskComposer api={apiWith(createTask)} ready={true} onCreated={noop} onOpenSetup={noop} />);
    await userEvent.type(screen.getByLabelText("Task"), "Open this");
    await userEvent.click(screen.getByRole("button", { name: "Start task" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("normal website address");
    expect((screen.getByLabelText("Task") as HTMLTextAreaElement).value).toBe("Open this");
  });

  it("fills the box from a suggestion and from a previous task", async () => {
    const { rerender } = render(<TaskComposer api={apiWith(vi.fn())} ready={true} onCreated={noop} onOpenSetup={noop} />);
    await userEvent.click(screen.getByRole("button", { name: /Look something up/ }));
    expect((screen.getByLabelText("Task") as HTMLTextAreaElement).value).toContain("Find the price");
    rerender(<TaskComposer api={apiWith(vi.fn())} ready={true} initial={{ instruction: "Run me again", startUrl: "a.com" }} onCreated={noop} onOpenSetup={noop} />);
    expect((screen.getByLabelText("Task") as HTMLTextAreaElement).value).toBe("Run me again");
  });
});
