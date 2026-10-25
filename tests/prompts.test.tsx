import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmationPrompt, CredentialPrompt, QuestionPrompt } from "../src/components/Prompts";

describe("ConfirmationPrompt", () => {
  it("shows the action and reasons, and reports the choice", async () => {
    const onRespond = vi.fn().mockResolvedValue(undefined);
    render(<ConfirmationPrompt action={'Click the button "Pay now"'} reasons={["Button would send payment details"]} onRespond={onRespond} />);
    expect(screen.getByText('Click the button "Pay now"')).toBeInTheDocument();
    expect(screen.getByText(/send payment details/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(onRespond).toHaveBeenCalledWith(false);
  });

  it("shows an error and lets the user retry if sending fails", async () => {
    const onRespond = vi.fn().mockRejectedValueOnce(new Error("Cannot reach the service")).mockResolvedValue(undefined);
    render(<ConfirmationPrompt action="Do it" reasons={[]} onRespond={onRespond} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Cannot reach the service")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onRespond).toHaveBeenCalledTimes(2);
  });
});

describe("CredentialPrompt", () => {
  it("masks what is typed, sends it once, and never keeps it on screen", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<CredentialPrompt label="Password" kind="password" onSubmit={onSubmit} onCancel={() => undefined} />);
    const input = screen.getByLabelText("Your password") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input).toHaveAttribute("autocomplete", "off");
    expect(screen.getByRole("button", { name: "Enter it" })).toBeDisabled();
    await userEvent.type(input, "hunter2");
    await userEvent.click(screen.getByRole("button", { name: "Enter it" }));
    expect(onSubmit).toHaveBeenCalledWith("hunter2");
    await waitFor(() => expect(input.value).toBe(""));
    expect(container.textContent).not.toContain("hunter2");
  });

  it("clears the box even when sending fails, and says so", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Not allowed"));
    render(<CredentialPrompt label="" kind="code" onSubmit={onSubmit} onCancel={() => undefined} />);
    const input = screen.getByLabelText("Your code") as HTMLInputElement;
    await userEvent.type(input, "123456");
    await userEvent.click(screen.getByRole("button", { name: "Enter it" }));
    expect(await screen.findByText("Not allowed")).toBeInTheDocument();
    expect(input.value).toBe("");
  });

  it("lets the user cancel the task instead", async () => {
    const onCancel = vi.fn();
    render(<CredentialPrompt label="Password" kind="password" onSubmit={vi.fn()} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel task" }));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("QuestionPrompt", () => {
  it("sends a trimmed answer", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<QuestionPrompt question="Which topic?" onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your answer"), "  Sales  ");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSubmit).toHaveBeenCalledWith("Sales");
  });
});
