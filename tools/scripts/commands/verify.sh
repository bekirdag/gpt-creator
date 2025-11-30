#!/usr/bin/env bash
# shellcheck shell=bash

cmd_verify() {
  gc_load_cmd qa
  warn "'verify' has been renamed to 'qa'; this alias will be removed in a future release."
  cmd_qa "$@"
}
