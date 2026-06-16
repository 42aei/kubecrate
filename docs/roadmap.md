# Roadmap

## Context

Kubecrate has a broad goal and a narrow first path.

The long-term goal is cluster-provider agnostic operation. The first path is kind-first so the initial work stays concrete and testable.

## Near-term direction

The early roadmap is about reducing ambiguity.

### 1. Define the install flow

Before adding implementation, the project needs a clear view of what point at a cluster and install means in practice.

That includes the boundary between bootstrap installation and GitOps-managed operation.

### 2. Define the local reference workflow

kind is the first local and reference path.

That does not change the long-term provider-agnostic goal, but it gives the project a realistic environment for the first installable slices.

### 3. Choose the minimal component set

The platform should start with the smallest useful set of platform services.

If a component does not help establish the baseline or validate the first installable slice, it should wait.

### 4. Create the first installable slice

The first real slice should be reviewable and useful on its own.

It should prove a small end-to-end path rather than build several horizontal layers in parallel.

## Current sequence

The current order is:

1. define repository and documentation structure
2. define install flow and kind-first local workflow
3. define bootstrap-to-GitOps lifecycle handling
4. define the platform services and application services model in working detail
5. choose the minimal component set
6. build the first installable slice

## Not in scope yet

This first pass does not settle every future component, provider path, or production concern.

The goal is to create enough structure for the next implementation proposal to stay small and reviewable.
