# The mail-only patch cannot release the SMTP alias. Forget its state without mutating Graph.
removed {
  from = msgraph_update_resource.mail

  lifecycle {
    destroy = false
  }
}
