# Roadmap

## Context

Kubecrate has a broad goal and a narrow first path.

The long-term goal is cluster-provider agnostic operation.

## Near-term direction

The early roadmap is about reducing ambiguity.

### 1. Define the install flow

Before adding implementation, the project needs a clear view of what point at a cluster and install means in practice.

That includes the boundary between bootstrap installation and GitOps-managed operation.

### 2. Choose the minimal component set

The platform should start with the smallest useful set of platform services.

If a component does not help establish the baseline or validate the first installable slice, it should wait.

For the first installable slice, the minimal baseline is the Flux bootstrap and GitOps-managed operation handoff proof. Secret projection and additional platform services wait until a later change has a clear operator-visible reason.

### 3. Create the first installable slice

The first real slice should be reviewable and useful on its own.

It should prove a small end-to-end path rather than build several horizontal layers in parallel.

## Current sequence

The current order is:

1. define repository and documentation structure
2. define install flow and bootstrap-to-GitOps lifecycle handling
3. define the platform services and application services model in working detail
4. choose the minimal component set
5. build the first installable slice
6. improve repository structure and conventions for reliable AI-agent handoff

## Not in scope yet

This first pass does not settle every future component, provider path, or production concern.

The goal is to create enough structure for the next implementation proposal to stay small and reviewable.
