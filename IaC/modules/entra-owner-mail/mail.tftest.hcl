mock_provider "msgraph" {}

variables {
  owner_object_id = "11111111-1111-1111-1111-111111111111"
  expected_identities = [
    { signInType = "federated", issuer = "MicrosoftAccount", issuerAssignedId = null },
    { signInType = "userPrincipalName", issuer = "example.onmicrosoft.com", issuerAssignedId = "rodman@stinkyboi.com" },
  ]
  replacement_mail = "owner@example.net"
  kms_key_id       = "alias/test"
  kms_region       = "us-east-1"
}

override_data {
  target = data.msgraph_resource.owner
  values = {
    output = {
      id             = "11111111-1111-1111-1111-111111111111"
      upn            = "rodman@stinkyboi.com"
      user_type      = "Member"
      creation_type  = "Invitation"
      external_state = "Accepted"
      enabled        = true
      identities = [
        { signInType = "federated", issuer = "MicrosoftAccount", issuerAssignedId = null },
        { signInType = "userPrincipalName", issuer = "example.onmicrosoft.com", issuerAssignedId = "rodman@stinkyboi.com" },
      ]
    }
  }
}

override_resource {
  target = msgraph_update_resource.mail
  values = {
    output = {
      id             = "11111111-1111-1111-1111-111111111111"
      upn            = "rodman@stinkyboi.com"
      user_type      = "Member"
      creation_type  = "Invitation"
      external_state = "Accepted"
      enabled        = true
      identities = [
        { signInType = "federated", issuer = "MicrosoftAccount", issuerAssignedId = null },
        { signInType = "userPrincipalName", issuer = "example.onmicrosoft.com", issuerAssignedId = "rodman@stinkyboi.com" },
      ]
    }
  }
}

run "patches_only_private_mail" {
  command = plan

  assert {
    condition = (
      msgraph_update_resource.mail.url == "users/${var.owner_object_id}" &&
      msgraph_update_resource.mail.update_method == "PATCH" &&
      nonsensitive(msgraph_update_resource.mail.body) == { mail = "owner@example.net" } &&
      issensitive(msgraph_update_resource.mail.body) &&
      msgraph_update_resource.mail.ignore_missing_property == false
    )
    error_message = "Only the exact existing owner's mail may be patched, and the entire body must remain sensitive."
  }
}

run "rejects_changed_owner_identity" {
  command = plan
  variables {
    expected_identities = [
      { signInType = "federated", issuer = "MicrosoftAccount", issuerAssignedId = null },
      { signInType = "userPrincipalName", issuer = "changed.onmicrosoft.com", issuerAssignedId = "rodman@stinkyboi.com" },
    ]
  }
  expect_failures = [msgraph_update_resource.mail]
}

run "permits_reviewed_mail_rollback" {
  command = plan
  variables {
    replacement_mail = "rodman@stuhlmuller.net"
  }
  assert {
    condition     = nonsensitive(msgraph_update_resource.mail.body) == { mail = "rodman@stuhlmuller.net" }
    error_message = "A reviewed rollback must be able to restore the original mailbox after releasing its address."
  }
}

run "rejects_another_object" {
  command = plan
  variables {
    owner_object_id = "22222222-2222-2222-2222-222222222222"
  }
  expect_failures = [msgraph_update_resource.mail]
}

run "rejects_missing_identity_readback" {
  command = plan
  override_resource {
    target = msgraph_update_resource.mail
    values = { output = {} }
  }
  expect_failures = [msgraph_update_resource.mail]
}
