resource "random_password" "initial" {
  length           = 40
  min_lower        = 3
  min_upper        = 3
  min_numeric      = 3
  min_special      = 3
  override_special = "!@#%*-_+="
}

# Creating a regular user supplies an internal Entra credential. This is not an
# invitation, conversion of an existing identity, or a service-license grant.
resource "azuread_user" "this" {
  user_principal_name     = var.user_principal_name
  display_name            = var.display_name
  mail_nickname           = split("@", var.user_principal_name)[0]
  account_enabled         = true
  password                = random_password.initial.result
  force_password_change   = true
  disable_strong_password = false

  lifecycle {
    prevent_destroy = true
    # The user owns the permanent password after their first interactive login.
    ignore_changes = [password, force_password_change]
  }
}
