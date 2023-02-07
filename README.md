# Marlin-Lazy-Build
Build Marlin firmware with Github Actions

## Steps

1. Fork this repo
2. Commit your modification to the submodule `Configurations` as you like
3. In Actions, dispatch the workflow manually
4. Get the compiled firmware in release

## Variables
| Name                               | Note                                                                                                                                    | Required |
|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|----------|
| Board environment                  | [Find the environment for your board](https://marlinfw.org/docs/basics/install_platformio_cli.html#find-the-environment-for-your-board) | Y        |
| Configuration directory            | Directory of all custom configuration `.h` files. Relative path to this repository.                                                     | Y        |
| Marlin Repository                  | Repository of Marlin. In GitHub `<username>/<repo>` format.                                                                             | Y        |
| Branch / tag / SHA to checkout     | Ref to brach / tag / SHA, eg. `bugfix-2.1.x`, `2.1.2`, `444259d`.                                                                       | N        |
| Release tag for compiled firmware  | Tag used to release the compiled firmware.                                                                                              | Y        |
| Release name for compiled firmware | Name used to release the compiled firmware. Default uses release tag.                                                                   | N        |
