# Run through Rails after schema preparation; never print the bootstrap password.
begin
  username = 'rodman'
  email = 'rodman@stuhlmuller.net'
  account = Account.find_local(username)
  if account
    user = account.user
    unless user && user.email == email && user.role&.name == 'Owner' && user.confirmed? && user.approved?
      abort 'Existing account does not match the declared owner; refusing replacement'
    end
    puts 'Declared Mastodon owner already exists; credentials preserved'
  else
    password = File.read('/run/mastodon/admin-password')
    abort 'Invalid owner bootstrap password' if password.length < 32 || password == 'REPLACE_ME'
    role = UserRole.find_by(name: 'Owner')
    abort 'Owner role seed is missing' unless role
    User.transaction do
      user = User.new(email: email, password: password, agreement: true,
                      role_id: role.id, confirmed_at: Time.now.utc,
                      bypass_registration_checks: true)
      user.account = Account.new(username: username)
      user.save!
      user.confirmed_at = nil
      user.mark_email_as_confirmed!
      user.approve!
    end
    puts 'Declared Mastodon owner created; password retained in protected SSM'
  end
rescue StandardError
  warn 'Mastodon owner bootstrap failed; private details withheld'
  exit 1
end
